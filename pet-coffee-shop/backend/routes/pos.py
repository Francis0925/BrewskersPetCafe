# Brewskers point of sale routes
# POS page, order history, receipt reprint and order creation

import datetime
import decimal

from flask import jsonify, render_template, request

from backend.auth import app, connect_db
from backend.config import ORDER_STATUSES, TAX_RATE
from backend.helpers import query, run
from backend.permissions import require


@app.get("/pos")
@require("pos.use")
def pos(user):
    products = query(
        "SELECT * FROM products WHERE status = 'available' AND stock > 0 ORDER BY category, name"
    )

    return render_template("pos.html", user=user, active="pos", title="Point of sale", products=products)


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


@app.post("/api/orders/<int:order_id>/status")
@require("orders.read")
def set_order_status(user, order_id):
    """Move an order between Queued, Completed and Cancelled."""
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "").strip().lower()

    if status not in ORDER_STATUSES:
        return jsonify(ok=False, error="Unknown status"), 400

    existing = query("SELECT order_id FROM orders WHERE order_id = ?", (order_id,), one=True)
    if not existing:
        return jsonify(ok=False, error="Order not found"), 404

    run("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))

    from backend.activity import record_activity

    record_activity(
        user_id=user["user_id"],
        action="order_status_changed",
        description=f"Set order {order_id} to {status}",
        entity_type="order",
        entity_id=order_id,
    )

    return jsonify(ok=True, status=status)


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
        subtotal = decimal.Decimal("0")
        order_lines = []

        for item in cart_items:
            try:
                product_id = int(item["product_id"])
                quantity = int(item["quantity"])
            except (KeyError, TypeError, ValueError):
                return jsonify(ok=False, error="Invalid cart item"), 400

            if product_id < 1 or quantity < 1:
                return jsonify(ok=False, error="Invalid cart quantity"), 400

            cursor.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
            product = cursor.fetchone()

            if not product or product["status"] != "available":
                return jsonify(ok=False, error="A product in the cart is unavailable"), 400

            if product["stock"] < quantity:
                return jsonify(ok=False, error=f"Not enough stock for {product['name']}"), 409

            price = decimal.Decimal(str(product["price"]))
            subtotal += price * quantity
            order_lines.append((product["product_id"], product["name"], quantity, price))

        subtotal = subtotal.quantize(cents, rounding=decimal.ROUND_HALF_UP)
        order_total = (subtotal * (1 + TAX_RATE)).quantize(cents, rounding=decimal.ROUND_HALF_UP)
        tax = order_total - subtotal

        if method == "cash":
            try:
                amount_paid = decimal.Decimal(str(data.get("amount_paid") or 0)).quantize(
                    cents, rounding=decimal.ROUND_HALF_UP
                )
            except decimal.InvalidOperation:
                return jsonify(ok=False, error="Enter a valid cash amount"), 400

            if amount_paid < order_total:
                return jsonify(ok=False, error="Amount tendered is less than the total"), 400
        else:
            amount_paid = order_total

        change = amount_paid - order_total

        order_no = "ORD-" + datetime.datetime.now().strftime("%y%m%d%H%M%S%f")[:14]

        cursor.execute(
            """INSERT INTO orders
                 (order_no, customer_name, total_amount,
                  payment_method, amount_paid, change_amount, created_by, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')""",
            (
                order_no,
                (data.get("customer_name") or "Walk-in").strip() or "Walk-in",
                float(order_total),
                method,
                float(amount_paid),
                float(change),
                user["user_id"],
            ),
        )

        order_id = cursor.lastrowid

        for product_id, _name, quantity, price in order_lines:
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                (order_id, product_id, quantity, float(price)),
            )
            cursor.execute(
                """UPDATE products
                      SET stock = stock - ?
                    WHERE product_id = ?
                      AND stock >= ?""",
                (quantity, product_id, quantity),
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Product stock changed during checkout")

        db.commit()

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
                {"name": name, "qty": quantity, "price": float(price)}
                for _id, name, quantity, price in order_lines
            ],
        )
    except Exception:
        db.rollback()
        app.logger.exception("Could not create order")
        return jsonify(ok=False, error="Could not save the order. Please try again."), 500
    finally:
        db.close()
