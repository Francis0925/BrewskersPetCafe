import datetime, decimal
from functools import wraps
from flask import render_template, request, jsonify, redirect
from auth import app, connect_db          # reuses the login/signup/reset routes in auth.py

LOW_STOCK_LIMIT = 5
TAX_RATE = decimal.Decimal("0.08")
APPOINTMENT_STATUSES = ("scheduled", "completed", "cancelled")

# ---------- database helpers ----------
def clean(row):
    for key, value in row.items():
        if isinstance(value, decimal.Decimal): row[key] = float(value)
        elif isinstance(value, datetime.timedelta): row[key] = str(value)[:-3].zfill(5)
        elif isinstance(value, datetime.date): row[key] = value.isoformat()
    return row

def query(sql, args=(), one=False):
    db = connect_db(); cursor = db.cursor(dictionary=True)
    cursor.execute(sql, args)
    rows = [clean(r) for r in cursor.fetchall()]
    db.close()
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    db = connect_db(); cursor = db.cursor()
    cursor.execute(sql, args); db.commit()
    new_id = cursor.lastrowid; db.close()
    return new_id

# ---------- login protection ----------
def current_user():
    token = request.cookies.get("session")
    if not token: return None
    return query("""SELECT u.user_id, u.username, u.role FROM users u
                    JOIN (SELECT user_id, token, expires_at FROM sessions
                          UNION SELECT user_id, token, expires_at FROM remember_tokens) t
                      ON t.user_id = u.user_id
                    WHERE t.token = %s AND t.expires_at > NOW()""", (token,), one=True)

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"): return jsonify(ok=False, error="Please log in"), 401
            return redirect("/")
        return view(user, *args, **kwargs)
    return wrapper

@app.get("/logout")
def logout():
    token = request.cookies.get("session")
    if token:
        run("DELETE FROM sessions WHERE token = %s", (token,))
        run("DELETE FROM remember_tokens WHERE token = %s", (token,))
    response = redirect("/"); response.delete_cookie("session")
    return response

# ---------- dashboard ----------
@app.get("/dashboard")
@login_required
def dashboard(user):
    today = datetime.date.today()
    todays_appointments = query("""SELECT a.*, s.name AS service_name FROM appointments a
        JOIN services s ON s.service_id = a.service_id
        WHERE a.appt_date = %s AND a.status != 'cancelled' ORDER BY a.appt_time""", (today,))
    sales = query("""SELECT COUNT(*) AS order_count, COALESCE(SUM(total_amount), 0) AS total_sales
                     FROM orders WHERE DATE(order_date) = %s""", (today,), one=True)
    low_stock_count = query("SELECT COUNT(*) AS n FROM products WHERE stock <= %s AND status != 'hidden'",
                            (LOW_STOCK_LIMIT,), one=True)["n"]
    top_seller = query("""SELECT p.name FROM order_items i JOIN orders o ON o.order_id = i.order_id
        JOIN products p ON p.product_id = i.product_id WHERE DATE(o.order_date) = %s
        GROUP BY p.product_id, p.name ORDER BY SUM(i.quantity) DESC LIMIT 1""", (today,), one=True)
    average_ticket = sales["total_sales"] / sales["order_count"] if sales["order_count"] else 0
    return render_template("dashboard.html", user=user, active="dashboard", title="Dashboard", today=today,
        appointments=todays_appointments, sales=sales, low_stock_count=low_stock_count,
        top_seller=top_seller["name"] if top_seller else "-", average_ticket=average_ticket)

# ---------- point of sale ----------
@app.get("/pos")
@login_required
def pos(user):
    products = query("SELECT * FROM products WHERE status = 'available' AND stock > 0 ORDER BY category, name")
    return render_template("pos.html", user=user, active="pos", title="Point of sale", products=products)

@app.post("/api/orders")
@login_required
def create_order(user):
    data = request.get_json(force=True)
    cart_items = data.get("items") or []
    if not cart_items: return jsonify(ok=False, error="The cart is empty")
    db = connect_db(); cursor = db.cursor(dictionary=True)
    try:
        order_total, order_lines = decimal.Decimal(0), []
        for item in cart_items:
            quantity = int(item["quantity"])
            cursor.execute("SELECT * FROM products WHERE product_id = %s FOR UPDATE", (item["product_id"],))
            product = cursor.fetchone()
            if not product or quantity < 1 or product["stock"] < quantity:
                db.rollback()
                return jsonify(ok=False, error=f"Not enough stock for {product['name'] if product else 'an item'}")
            order_total += product["price"] * quantity
            order_lines.append((product["product_id"], quantity, product["price"]))
        order_total = (order_total * (1 + TAX_RATE)).quantize(decimal.Decimal("0.01"))   # price + 8% tax
        amount_paid = decimal.Decimal(str(data.get("amount_paid") or order_total))
        if amount_paid < order_total:
            return jsonify(ok=False, error="Amount paid is less than the total")
        order_no = "ORD-" + datetime.datetime.now().strftime("%y%m%d%H%M%S")
        cursor.execute("""INSERT INTO orders (order_no, customer_name, total_amount, payment_method, amount_paid, change_amount)
                          VALUES (%s, %s, %s, %s, %s, %s)""",
            (order_no, (data.get("customer_name") or "Walk-in").strip(), order_total,
             data.get("payment_method", "cash"), amount_paid, amount_paid - order_total))
        order_id = cursor.lastrowid
        for product_id, quantity, price in order_lines:
            cursor.execute("INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s, %s, %s, %s)",
                           (order_id, product_id, quantity, price))
            cursor.execute("UPDATE products SET stock = stock - %s WHERE product_id = %s", (quantity, product_id))
        db.commit()
        return jsonify(ok=True, order_no=order_no, total=float(order_total), change=float(amount_paid - order_total))
    finally:
        db.close()

# ---------- inventory ----------
@app.get("/inventory")
@login_required
def inventory(user):
    products = query("SELECT * FROM products WHERE status != 'hidden' ORDER BY category, name")
    return render_template("inventory.html", user=user, active="inventory", title="Inventory",
                           products=products, low_stock_limit=LOW_STOCK_LIMIT)

@app.post("/api/products")
@login_required
def add_product(user):
    data = request.get_json(force=True)
    name, category = (data.get("name") or "").strip(), (data.get("category") or "").strip()
    try: price, stock = float(data.get("price")), int(data.get("stock") or 0)
    except (TypeError, ValueError): return jsonify(ok=False, error="Price and stock must be numbers")
    if not name or not category or price < 0 or stock < 0:
        return jsonify(ok=False, error="Fill in name, category, price and stock")
    run("INSERT INTO products (category, name, price, stock, emoji) VALUES (%s, %s, %s, %s, %s)",
        (category, name, price, stock, (data.get("emoji") or "☕").strip()))
    return jsonify(ok=True)

@app.post("/api/products/<int:product_id>/stock")
@login_required
def set_stock(user, product_id):
    stock = int(request.get_json(force=True).get("stock", -1))
    if stock < 0: return jsonify(ok=False, error="Stock cannot be negative")
    run("UPDATE products SET stock = %s WHERE product_id = %s", (stock, product_id))
    return jsonify(ok=True)

@app.delete("/api/products/<int:product_id>")
@login_required
def remove_product(user, product_id):
    run("UPDATE products SET status = 'hidden' WHERE product_id = %s", (product_id,))   # hidden, so old orders keep working
    return jsonify(ok=True)

# ---------- appointments & schedule ----------
APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name FROM appointments a
    JOIN services s ON s.service_id = a.service_id {where} ORDER BY a.appt_date, a.appt_time"""

@app.get("/appointments")
@login_required
def appointments(user):
    upcoming = query(APPOINTMENT_SQL.format(where="WHERE a.appt_date >= CURDATE() AND a.status = 'scheduled'"))
    return render_template("appointments.html", user=user, active="appointments", title="Appointments",
                           appointments=upcoming, services=query("SELECT * FROM services ORDER BY name"))

@app.get("/schedule")
@login_required
def schedule(user):
    everything = query(APPOINTMENT_SQL.format(where="WHERE a.status != 'cancelled'"))
    return render_template("schedule.html", user=user, active="appointments", title="Schedule",
                           appointments=everything, services=query("SELECT * FROM services ORDER BY name"))

@app.post("/api/appointments")
@login_required
def add_appointment(user):
    data = request.get_json(force=True)
    needed = ("pet_name", "owner_name", "phone", "service_id", "appt_date", "appt_time")
    if not all((data.get(field) or "").strip() for field in needed):
        return jsonify(ok=False, error="Please fill in every required field")
    run("""INSERT INTO appointments (pet_name, pet_type, breed, pet_age, owner_name, phone, service_id, appt_date, appt_time, notes, photo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (data["pet_name"].strip(), data.get("pet_type", "Dog"), data.get("breed", ""), data.get("pet_age", ""),
         data["owner_name"].strip(), data["phone"].strip(),
         data["service_id"], data["appt_date"], data["appt_time"], data.get("notes", ""),
         data.get("photo") or None))
    return jsonify(ok=True)

@app.post("/api/appointments/<int:appointment_id>/status")
@login_required
def set_appointment_status(user, appointment_id):
    status = request.get_json(force=True).get("status")
    if status not in APPOINTMENT_STATUSES: return jsonify(ok=False, error="Unknown status")
    run("UPDATE appointments SET status = %s WHERE appointment_id = %s", (status, appointment_id))
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(debug=True)
