# Brewskers point of sale routes
# POS page, order history, receipt reprint and order creation

import datetime
import decimal

from flask import jsonify, render_template, request

from backend.auth import app, connect_db
from backend.algorithms import merge_sort
from backend.config import ORDER_STATUSES
from backend.errors import InsufficientPaymentError, OutOfStockError
from backend.helpers import query, run
from backend.models import Cart, Product
from backend.permissions import require
from backend.pos_state import order_queue, product_index, status_undo
from backend.settings import get_store_settings


@app.get("/pos")
@require("pos.use")
def pos(user):
    # The product grid comes from the hash table, and every row becomes a
    # Product object that owns its own rules. The template still receives
    # plain dictionaries from to_dict(). The tax rate and low stock
    # threshold are injected so the cart preview and the low stock badges
    # always match what the server will charge and flag.
    settings = get_store_settings()
    products = [Product.from_row(row).to_dict() for row in product_index.sellable()]

    return render_template(
        "pos.html",
        user=user,
        active="pos",
        title="Point of sale",
        products=products,
        tax_rate_percent=settings.tax_rate_percent,
        low_stock_limit=settings.low_stock_limit,
    )


@app.get("/orders")
@require("orders.read")
def order_history(user):
    """Queued orders page. New POS orders start here as queued."""
    return _render_orders(user, page="queued")


@app.get("/orders/history")
@require("orders.read")
def order_history_page(user):
    """Order history page for completed and cancelled orders."""
    return _render_orders(user, page="history")


def _render_orders(user, page):
    status_filter = (request.args.get("status") or "").strip().lower()
    search = (request.args.get("q") or "").strip()

    # Queued page defaults to queued, history page defaults to completed/cancelled.
    if not status_filter:
        status_filter = "queued" if page == "queued" else "completed"

    sql = """SELECT o.*, u.username AS cashier_name
             FROM orders o
             LEFT JOIN users u ON u.user_id = o.created_by
             WHERE 1 = 1"""
    args = []

    if status_filter in ORDER_STATUSES:
        sql += " AND COALESCE(o.status, 'completed') = ?"
        args.append(status_filter)

    if search:
        sql += " AND (o.order_no LIKE ? OR COALESCE(o.customer_name, '') LIKE ?)"
        args.extend([f"%{search}%", f"%{search}%"])

    sql += " ORDER BY o.order_date DESC, o.order_id DESC LIMIT 100"

    recent_orders = query(sql, tuple(args))

    # The queued list is shown in queue order (oldest first) with a place in line.
    if status_filter == "queued":
        for order in recent_orders:
            order["queue_position"] = order_queue.position(order["order_id"])
        recent_orders = merge_sort(recent_orders, key=lambda o: (o["queue_position"] is None, o["queue_position"] or 0))

    counts = query(
        """SELECT COALESCE(status, 'completed') AS status, COUNT(*) AS n
             FROM orders GROUP BY COALESCE(status, 'completed')"""
    )
    count_by_status = {row["status"]: row["n"] for row in counts}

    title = "Queued orders" if page == "queued" else "Order history"
    return render_template(
        "order_history.html",
        user=user,
        active="orders" if page == "queued" else "history",
        title=title,
        page=page,
        orders=recent_orders,
        status_filter=status_filter,
        search=search,
        count_by_status=count_by_status,
        order_statuses=ORDER_STATUSES,
    )


def _apply_status(user, order_id, status, record_undo=True):
    """Change an order's status and keep the Queue and undo Stack in step.

    Returns (previous_status, error_message, http_code).
    """
    existing = query("SELECT order_id, order_no, customer_name, order_date, COALESCE(status, 'completed') AS status "
                     "FROM orders WHERE order_id = ?", (order_id,), one=True)
    if not existing:
        return None, "Order not found", 404

    previous = existing["status"]

    run("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))

    # Queue: leaving "queued" removes the order from the line, entering it joins the back.
    if previous == "queued" and status != "queued":
        order_queue.remove(order_id)
    elif previous != "queued" and status == "queued":
        order_queue.enqueue({
            "order_id": existing["order_id"],
            "order_no": existing["order_no"],
            "customer_name": existing["customer_name"],
            "order_date": existing["order_date"],
        })

    # Stack: remember what to go back to.
    if record_undo and previous != status:
        status_undo.push(user["user_id"], order_id, previous)

    from backend.activity import record_activity

    record_activity(
        user_id=user["user_id"],
        action="order_status_changed",
        description=f"Set order {order_id} to {status}",
        entity_type="order",
        entity_id=order_id,
    )

    return previous, None, 200


@app.post("/api/orders/<int:order_id>/status")
@require("orders.read")
def set_order_status(user, order_id):
    """Move an order between Queued, Completed and Cancelled."""
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "").strip().lower()

    if status not in ORDER_STATUSES:
        return jsonify(ok=False, error="Unknown status"), 400

    _previous, error, code = _apply_status(user, order_id, status)
    if error:
        return jsonify(ok=False, error=error), code

    return jsonify(ok=True, status=status, can_undo=status_undo.depth(user["user_id"]) > 0)


@app.post("/api/orders/next/complete")
@require("orders.read")
def complete_next_order(user):
    """Dequeue the order at the front of the line and mark it completed."""
    order = order_queue.dequeue()

    if order is None:
        return jsonify(ok=False, error="No queued orders"), 404

    # Already dequeued, so only the database and the undo stack need updating.
    run("UPDATE orders SET status = 'completed' WHERE order_id = ?", (order["order_id"],))
    status_undo.push(user["user_id"], order["order_id"], "queued")

    from backend.activity import record_activity

    record_activity(
        user_id=user["user_id"],
        action="order_status_changed",
        description=f"Set order {order['order_id']} to completed",
        entity_type="order",
        entity_id=order["order_id"],
    )

    return jsonify(ok=True, order_no=order["order_no"], status="completed")


@app.post("/api/orders/undo")
@require("orders.read")
def undo_order_status(user):
    """Pop the last status change this user made and put the order back."""
    entry = status_undo.pop(user["user_id"])

    if entry is None:
        return jsonify(ok=False, error="Nothing to undo"), 404

    order_id, previous_status = entry
    _prev, error, code = _apply_status(user, order_id, previous_status, record_undo=False)

    if error:
        return jsonify(ok=False, error=error), code

    return jsonify(ok=True, order_id=order_id, status=previous_status)


@app.get("/api/orders/<int:order_id>/receipt")
@require("orders.reprint")
def order_receipt(user, order_id):
    """Return a saved order formatted for receipt rendering."""
    order = query(
        """SELECT o.*, u.username AS cashier_name
             FROM orders o
             LEFT JOIN users u ON u.user_id = o.created_by
            WHERE o.order_id = ?""",
        (order_id,),
        one=True,
    )

    if not order:
        return jsonify(ok=False, error="Order not found"), 404

    items = query(
        """SELECT oi.product_id, oi.quantity, oi.price,
                  COALESCE(p.name, 'Removed product') AS name
             FROM order_items oi
             LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.item_id""",
        (order_id,),
    )

    subtotal = round(sum(float(item["price"]) * int(item["quantity"]) for item in items), 2)
    tax = round(float(order["total_amount"]) - subtotal, 2)

    return jsonify(
        ok=True,
        receipt={
            "order_id": order["order_id"],
            "order_no": order["order_no"],
            "customer_name": order["customer_name"] or "Walk-in",
            "order_date": order["order_date"],
            "cashier_name": order["cashier_name"] or "Unknown cashier",
            "payment_method": order["payment_method"],
            "status": order.get("status") or "completed",
            "subtotal": subtotal,
            "tax": tax,
            "tax_rate": order.get("tax_rate"),
            "total": float(order["total_amount"]),
            "amount_paid": order["amount_paid"],
            "change_amount": order["change_amount"],
            "items": [
                {
                    "name": item["name"],
                    "quantity": int(item["quantity"]),
                    "unit_price": float(item["price"]),
                    "line_total": round(float(item["price"]) * int(item["quantity"]), 2),
                }
                for item in items
            ],
        },
    )


@app.post("/api/orders")
@require("pos.use")
def create_order(user):
    data = request.get_json(force=True) or {}
    cart_items = data.get("items") or []

    if not cart_items:
        return jsonify(ok=False, error="The cart is empty"), 400

    method = data.get("payment_method", "cash")

    if method not in ("cash", "gcash", "card"):
        return jsonify(ok=False, error="Unknown payment method"), 400

    cents = decimal.Decimal("0.01")
    db = connect_db()
    cursor = db.cursor()

    try:
        # The Cart object owns the running totals, and every product row
        # becomes a Product object that guards its own availability and
        # stock. The tax rate comes from the store settings, so the charge
        # always matches what administrators configured.
        settings = get_store_settings()
        cart = Cart(tax_rate=settings.tax_rate_fraction)

        for item in cart_items:
            try:
                product_id = int(item["product_id"])
                quantity = int(item["quantity"])
            except (KeyError, TypeError, ValueError):
                return jsonify(ok=False, error="Invalid cart item"), 400

            if product_id < 1 or quantity < 1:
                return jsonify(ok=False, error="Invalid cart quantity"), 400

            # Hash table lookup instead of a query per cart line, then the
            # row becomes a Product object that guards its own rules.
            row = product_index.get(product_id)

            if not row:
                return jsonify(ok=False, error="A product in the cart is unavailable"), 400

            product = Product.from_row(row)

            if not product.is_available():
                return jsonify(ok=False, error="A product in the cart is unavailable"), 400

            # Raises OutOfStockError when the shelf cannot cover the line.
            product.reduce_stock(quantity)

            cart.add(product, quantity)

        subtotal = cart.subtotal
        order_total = cart.total
        tax = cart.tax

        if method == "cash":
            try:
                amount_paid = decimal.Decimal(str(data.get("amount_paid") or 0)).quantize(
                    cents, rounding=decimal.ROUND_HALF_UP
                )
            except decimal.InvalidOperation:
                return jsonify(ok=False, error="Enter a valid cash amount"), 400

            if amount_paid < order_total:
                raise InsufficientPaymentError(order_total, amount_paid)
        else:
            amount_paid = order_total

        change = amount_paid - order_total

        order_no = "ORD-" + datetime.datetime.now().strftime("%y%m%d%H%M%S%f")[:14]

        cursor.execute(
            """INSERT INTO orders
                 (order_no, customer_name, total_amount,
                  payment_method, amount_paid, change_amount, created_by,
                  status, tax_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
            (
                order_no,
                (data.get("customer_name") or "Walk-in").strip() or "Walk-in",
                float(order_total),
                method,
                float(amount_paid),
                float(change),
                user["user_id"],
                settings.tax_rate_percent,
            ),
        )

        order_id = cursor.lastrowid

        for line in cart.lines:
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                (order_id, line.product.product_id, line.quantity, float(line.unit_price)),
            )
            cursor.execute(
                """UPDATE products
                      SET stock = stock - ?
                    WHERE product_id = ?
                      AND stock >= ?""",
                (line.quantity, line.product.product_id, line.quantity),
            )

            if cursor.rowcount != 1:
                # The shelf changed while the order was being saved.
                raise OutOfStockError(line.product.name, line.quantity, 0)

        db.commit()

        # Stock changed, so refresh the product table. The new order joins the
        # back of the queue.
        product_index.invalidate()
        order_queue.enqueue({
            "order_id": order_id,
            "order_no": order_no,
            "customer_name": (data.get("customer_name") or "Walk-in").strip() or "Walk-in",
            "order_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        return jsonify(
            ok=True,
            order_no=order_no,
            status="queued",
            method=method,
            subtotal=float(subtotal),
            tax=float(tax),
            total=float(order_total),
            paid=float(amount_paid),
            change=float(change),
            lines=[
                {"name": line.product.name, "qty": line.quantity, "price": float(line.unit_price)}
                for line in cart.lines
            ],
        )
    except OutOfStockError as error:
        db.rollback()
        return jsonify(ok=False, error=f"Not enough stock for {error.name}"), 409
    except InsufficientPaymentError:
        db.rollback()
        return jsonify(ok=False, error="Amount tendered is less than the total"), 400
    except Exception:
        db.rollback()
        app.logger.exception("Could not create order")
        return jsonify(ok=False, error="Could not save the order. Please try again."), 500
    finally:
        db.close()
