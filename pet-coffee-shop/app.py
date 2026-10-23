# Brewskers — main app
# Dashboard, POS, inventory, appointments, schedule, services, reports,
# staff management, and profile.

import datetime
import decimal
import os
from functools import wraps

from flask import render_template, request, jsonify, redirect

from auth import (
    app, connect_db, hash_pw,
    create_user, list_users, set_user_role, set_user_active,
    change_password, make_default_password
)


# --- config ---------------------------------------------------------------

LOW_STOCK_LIMIT = 5
TAX_RATE = decimal.Decimal("0.08")
APPOINTMENT_STATUSES = ("scheduled", "completed", "cancelled")

ROLES = ("admin", "cashier", "inventory", "appointments", "viewer")

# Role -> permission keys. "*" means all permissions.
PERMISSIONS = {
    "admin": {"*"},
    "cashier": {
        "dashboard.read",
        "pos.use",
    },
    "inventory": {
        "dashboard.read",
        "inventory.read",
        "inventory.write",
    },
    "appointments": {
        "dashboard.read",
        "appointments.read",
        "appointments.write",
        "services.read",
    },
    "viewer": {
        "dashboard.read",
        "inventory.read",
        "appointments.read",
    },
}

# Sidebar nav items: (key, url, label, permission, svg)
NAV_ITEMS = [
    ("dashboard", "/dashboard", "Dashboard", "dashboard.read",
        '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>'),
    ("pos", "/pos", "Point of sale", "pos.use",
        '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/>'),
    ("inventory", "/inventory", "Inventory", "inventory.read",
        '<path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z"/><path d="M3.3 7 12 12l8.7-5M12 22V12"/>'),
]

# Where each role lands after login.
LANDING_PAGE = {
    "admin":        "/dashboard",
    "cashier":      "/pos",
    "inventory":    "/inventory",
    "appointments": "/appointments",
    "viewer":       "/dashboard",
}


# --- register template globals -------------------------------------------

# Expose the permission check to all templates so base.html can filter
# sidebar items and the profile popup can show admin-only links.
app.jinja_env.globals["user_has"] = (
    lambda user, perm: (
        user is not None
        and ("*" in PERMISSIONS.get(user.get("role", ""), set())
             or perm in PERMISSIONS.get(user.get("role", ""), set()))
    )
)


# --- db utilities ---------------------------------------------------------

def clean(row):
    row = dict(row)
    for key, value in list(row.items()):
        if isinstance(value, decimal.Decimal):
            row[key] = float(value)
        elif isinstance(value, datetime.timedelta):
            row[key] = str(value)[:-3].zfill(5)
        elif isinstance(value, datetime.date):
            row[key] = value.isoformat()
    return row


def query(sql, args=(), one=False, default=None):
    db = connect_db()
    rows = [clean(r) for r in db.execute(sql, args).fetchall()]
    db.close()
    if one:
        return rows[0] if rows else default
    return rows


def run(sql, args=()):
    db = connect_db()
    cur = db.cursor()
    cur.execute(sql, args)
    new_id = cur.lastrowid
    db.commit()
    db.close()
    return new_id


# --- session / permissions ------------------------------------------------

def current_user():
    token = request.cookies.get("session")
    if not token:
        return None
    db = connect_db()
    row = db.execute(
        """SELECT u.user_id, u.username, u.email, u.role, u.must_change_password
             FROM users u
             JOIN (
                 SELECT user_id, token, expires_at FROM sessions
                 UNION
                 SELECT user_id, token, expires_at FROM remember_tokens
             ) t ON t.user_id = u.user_id
            WHERE t.token = ? AND t.expires_at > datetime('now', 'localtime')""",
        (token,)
    ).fetchone()
    db.close()
    if not row:
        return None
    return dict(row)


def user_has(user, perm):
    if not user:
        return False
    perms = PERMISSIONS.get(user.get("role", ""), set())
    return "*" in perms or perm in perms


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Please log in"), 401
            return redirect("/")
        return view(user, *args, **kwargs)
    return wrapper


def require(perm):
    """Must be logged in, not on a temp password, and have this permission."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify(ok=False, error="Please log in"), 401
                return redirect("/")
            if user["must_change_password"] and not request.path.startswith(
                ("/first-login", "/api/profile/change-password", "/logout", "/static")
            ):
                return redirect("/first-login")
            if not user_has(user, perm):
                if request.path.startswith("/api/"):
                    return jsonify(ok=False, error="Not allowed"), 403
                return redirect("/dashboard")
            return view(user, *args, **kwargs)
        return wrapper
    return deco


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Admins only"), 403
            return redirect("/dashboard")
        return view(user, *args, **kwargs)
    return wrapper


# --- logout ---------------------------------------------------------------

@app.get("/logout")
def logout():
    token = request.cookies.get("session")
    if token:
        db = connect_db()
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.execute("DELETE FROM remember_tokens WHERE token = ?", (token,))
        db.commit()
        db.close()
    resp = redirect("/")
    resp.delete_cookie("session")
    return resp


# --- first login (forced password change) --------------------------------

@app.get("/first-login")
def first_login_page():
    user = current_user()
    if not user:
        return redirect("/")
    if not user["must_change_password"]:
        return redirect("/dashboard")
    return render_template(
        "first_login.html", user=user, title="Set your password"
    )


@app.post("/api/profile/change-password")
@login_required
def api_change_password():
    user = current_user()
    data = request.get_json(force=True)
    new_password = (data.get("new_password") or "").strip()
    confirm = (data.get("confirm") or "").strip()
    if len(new_password) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters")
    if new_password != confirm:
        return jsonify(ok=False, error="Passwords do not match")
    change_password(user["user_id"], new_password)
    return jsonify(ok=True)


# --- role-based landing after login --------------------------------------

@app.get("/landing")
def landing():
    user = current_user()
    if not user:
        return redirect("/")
    if user["must_change_password"]:
        return redirect("/first-login")
    return redirect(LANDING_PAGE.get(user["role"], "/dashboard"))


# --- profile --------------------------------------------------------------

@app.get("/profile")
@login_required
def profile_page(user):
    full = query(
        "SELECT user_id, username, email, role, created_at, last_login_at "
        "FROM users WHERE user_id = ?",
        (user["user_id"],), one=True
    )
    return render_template(
        "profile.html", user=full or user,
        title="My profile", active="profile"
    )


# --- admin: staff management ---------------------------------------------

@app.get("/admin/staff")
@admin_required
def admin_staff_page(user):
    rows = list_users()
    staff = [
        {
            "user_id": r["user_id"],
            "username": r["username"],
            "email": r["email"],
            "role": r["role"],
            "must_change_password": bool(r["must_change_password"]),
            "deactivated_at": r["deactivated_at"],
            "created_at": r["created_at"],
            "last_login_at": r["last_login_at"],
        }
        for r in rows
    ]
    return render_template(
        "admin_staff.html", user=user, active="admin",
        title="Staff", staff=staff, roles=ROLES
    )


@app.post("/api/admin/staff")
@admin_required
def api_admin_create_staff(user):
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    role = (data.get("role") or "cashier").strip()
    phrase = (data.get("phrase") or username).strip()

    if not username or not email:
        return jsonify(ok=False, error="Username and email are required")
    if role not in ROLES or role == "admin":
        return jsonify(ok=False, error="Invalid role")
    if "@" not in email or "." not in email:
        return jsonify(ok=False, error="Invalid email")

    temp_password = make_default_password(phrase)
    new_id = create_user(
        username=username, email=email, password=temp_password,
        role=role, created_by=user["user_id"], must_change_password=True
    )
    if not new_id:
        return jsonify(ok=False, error="Username or email already exists")
    return jsonify(ok=True, temp_password=temp_password, user_id=new_id)


@app.post("/api/admin/staff/<int:user_id>/role")
@admin_required
def api_admin_set_role(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(ok=False, error="You can't change your own role")
    data = request.get_json(force=True)
    role = (data.get("role") or "").strip()
    if role not in ROLES or role == "admin":
        return jsonify(ok=False, error="Invalid role")
    set_user_role(user_id, role)
    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/toggle-active")
@admin_required
def api_admin_toggle_active(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(ok=False, error="You can't deactivate yourself")
    data = request.get_json(force=True) or {}
    active = bool(data.get("active", True))
    set_user_active(user_id, active)
    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/reset-password")
@admin_required
def api_admin_reset_password(user, user_id):
    data = request.get_json(force=True) or {}
    phrase = (data.get("phrase") or "").strip()
    row = query(
        "SELECT username FROM users WHERE user_id = ?",
        (user_id,), one=True
    )
    if not row:
        return jsonify(ok=False, error="User not found")
    seed_phrase = phrase or row["username"]
    temp_password = make_default_password(seed_phrase)
    db = connect_db()
    db.execute(
        "UPDATE users SET password = ?, must_change_password = 1 "
        "WHERE user_id = ?",
        (hash_pw(temp_password), user_id)
    )
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM remember_tokens WHERE user_id = ?", (user_id,))
    db.commit()
    db.close()
    return jsonify(ok=True, temp_password=temp_password)


# --- dashboard ------------------------------------------------------------

@app.get("/dashboard")
@require("dashboard.read")
def dashboard(user):
    today = datetime.date.today()
    todays_appointments = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date = ? AND a.status != 'cancelled'
            ORDER BY a.appt_time""",
        (today,)
    )
    sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders WHERE DATE(order_date) = ?""",
        (today,), one=True, default={"order_count": 0, "total_sales": 0}
    )
    low_stock_count = query(
        "SELECT COUNT(*) AS n FROM products "
        "WHERE stock <= ? AND status != 'hidden'",
        (LOW_STOCK_LIMIT,), one=True, default={"n": 0}
    )["n"]
    top_seller = query(
        """SELECT p.name
             FROM order_items i
             JOIN orders o   ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) = ?
            GROUP BY p.product_id, p.name
            ORDER BY SUM(i.quantity) DESC LIMIT 1""",
        (today,), one=True
    )
    average_ticket = (
        sales["total_sales"] / sales["order_count"]
        if sales["order_count"] else 0
    )
    return render_template(
        "dashboard.html",
        user=user, active="dashboard", title="Dashboard",
        today=today, appointments=todays_appointments,
        sales=sales, low_stock_count=low_stock_count,
        top_seller=top_seller["name"] if top_seller else "-",
        average_ticket=average_ticket
    )


# --- point of sale --------------------------------------------------------

@app.get("/pos")
@require("pos.use")
def pos(user):
    products = query(
        "SELECT * FROM products WHERE status = 'available' AND stock > 0 "
        "ORDER BY category, name"
    )
    return render_template(
        "pos.html", user=user, active="pos",
        title="Point of sale", products=products
    )


@app.post("/api/orders")
@require("pos.use")
def create_order(user):
    data = request.get_json(force=True)
    cart_items = data.get("items") or []
    if not cart_items:
        return jsonify(ok=False, error="The cart is empty")
    db = connect_db()
    cur = db.cursor()
    try:
        order_total = decimal.Decimal(0)
        order_lines = []
        for item in cart_items:
            quantity = int(item["quantity"])
            cur.execute(
                "SELECT * FROM products WHERE product_id = ?",
                (item["product_id"],)
            )
            product = cur.fetchone()
            if not product or quantity < 1 or product["stock"] < quantity:
                db.rollback()
                return jsonify(ok=False, error=(
                    f"Not enough stock for "
                    f"{product['name'] if product else 'an item'}"
                ))
            order_total += product["price"] * quantity
            order_lines.append(
                (product["product_id"], quantity, product["price"])
            )
        order_total = (order_total * (1 + TAX_RATE)).quantize(
            decimal.Decimal("0.01")
        )
        amount_paid = decimal.Decimal(
            str(data.get("amount_paid") or order_total)
        )
        if amount_paid < order_total:
            return jsonify(ok=False, error="Amount paid is less than the total")
        order_no = "ORD-" + datetime.datetime.now().strftime("%y%m%d%H%M%S")
        cur.execute(
            """INSERT INTO orders
                 (order_no, customer_name, total_amount, payment_method,
                  amount_paid, change_amount, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (order_no,
             (data.get("customer_name") or "Walk-in").strip(),
             order_total, data.get("payment_method", "cash"),
             amount_paid, amount_paid - order_total,
             user["user_id"])
        )
        order_id = cur.lastrowid
        for product_id, quantity, price in order_lines:
            cur.execute(
                "INSERT INTO order_items "
                "(order_id, product_id, quantity, price) "
                "VALUES (?, ?, ?, ?)",
                (order_id, product_id, quantity, price)
            )
            cur.execute(
                "UPDATE products SET stock = stock - ? WHERE product_id = ?",
                (quantity, product_id)
            )
        db.commit()
        return jsonify(
            ok=True, order_no=order_no,
            total=float(order_total), change=float(amount_paid - order_total)
        )
    finally:
        db.close()


# --- inventory ------------------------------------------------------------

@app.get("/inventory")
@require("inventory.read")
def inventory(user):
    products = query(
        "SELECT * FROM products WHERE status != 'hidden' "
        "ORDER BY category, name"
    )
    return render_template(
        "inventory.html", user=user, active="inventory",
        title="Inventory", products=products,
        low_stock_limit=LOW_STOCK_LIMIT
    )


@app.post("/api/products")
@require("inventory.write")
def add_product(user):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    try:
        price = float(data.get("price"))
        stock = int(data.get("stock") or 0)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Price and stock must be numbers")
    if not name or not category or price < 0 or stock < 0:
        return jsonify(ok=False, error="Fill in name, category, price and stock")
    run(
        "INSERT INTO products (category, name, price, stock, emoji) "
        "VALUES (?, ?, ?, ?, ?)",
        (category, name, price, stock,
         (data.get("emoji") or "☕").strip())
    )
    return jsonify(ok=True)


@app.post("/api/products/<int:product_id>/stock")
@require("inventory.write")
def set_stock(user, product_id):
    stock = int(request.get_json(force=True).get("stock", -1))
    if stock < 0:
        return jsonify(ok=False, error="Stock cannot be negative")
    run(
        "UPDATE products SET stock = ? WHERE product_id = ?",
        (stock, product_id)
    )
    return jsonify(ok=True)


@app.delete("/api/products/<int:product_id>")
@require("inventory.write")
def remove_product(user, product_id):
    run(
        "UPDATE products SET status = 'hidden' WHERE product_id = ?",
        (product_id,)
    )
    return jsonify(ok=True)


# --- appointments + schedule ---------------------------------------------

APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name
                        FROM appointments a
                        JOIN services s ON s.service_id = a.service_id
                        {where}
                       ORDER BY a.appt_date, a.appt_time"""


@app.get("/appointments")
@require("appointments.read")
def appointments(user):
    upcoming = query(APPOINTMENT_SQL.format(
        where="WHERE a.appt_date >= date('now', 'localtime') "
              "AND a.status = 'scheduled'"
    ))
    return render_template(
        "appointments.html", user=user, active="appointments",
        title="Appointments", appointments=upcoming,
        services=query("SELECT * FROM services WHERE active = 1 ORDER BY name")
    )


@app.get("/schedule")
@require("appointments.read")
def schedule(user):
    everything = query(APPOINTMENT_SQL.format(
        where="WHERE a.status != 'cancelled'"
    ))
    return render_template(
        "schedule.html", user=user, active="schedule",
        title="Schedule", appointments=everything,
        services=query("SELECT * FROM services WHERE active = 1 ORDER BY name")
    )


@app.post("/api/appointments")
@require("appointments.write")
def add_appointment(user):
    data = request.get_json(force=True)
    needed = ("pet_name", "owner_name", "phone",
              "service_id", "appt_date", "appt_time")
    if not all((data.get(field) or "").strip() for field in needed):
        return jsonify(ok=False, error="Please fill in every required field")
    run(
        """INSERT INTO appointments
             (pet_name, pet_type, breed, pet_age, owner_name, phone,
              service_id, appt_date, appt_time, notes, photo, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["pet_name"].strip(),
         data.get("pet_type", "Dog"),
         data.get("breed", ""),
         data.get("pet_age", ""),
         data["owner_name"].strip(),
         data["phone"].strip(),
         data["service_id"],
         data["appt_date"],
         data["appt_time"],
         data.get("notes", ""),
         data.get("photo") or None,
         user["user_id"])
    )
    return jsonify(ok=True)


@app.post("/api/appointments/<int:appointment_id>/status")
@require("appointments.write")
def set_appointment_status(user, appointment_id):
    status = request.get_json(force=True).get("status")
    if status not in APPOINTMENT_STATUSES:
        return jsonify(ok=False, error="Unknown status")
    run(
        "UPDATE appointments SET status = ? WHERE appointment_id = ?",
        (status, appointment_id)
    )
    return jsonify(ok=True)


# --- services catalog ----------------------------------------------------
#
# View rules:
#   - Admin          : full read + write access
#   - Appointment    : read-only (can view services when creating bookings)
#   - Other roles    : no access
#
# The HTML template checks user.role == 'admin' to decide whether to show
# the "Add service", "Edit", and "Hide" buttons. The backend still enforces
# the permission on every write call.

@app.get("/services")
@require("services.read")
def services_page(user):
    services = query("SELECT * FROM services ORDER BY name")
    return render_template(
        "services.html", user=user, active="services",
        title="Services", services=services
    )


@app.post("/api/services")
@admin_required
def add_service(user):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    try:
        price = float(data.get("price"))
        duration = int(data.get("duration") or 30)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Price and duration must be numbers")
    if not name or price < 0 or duration <= 0:
        return jsonify(ok=False, error="Fill in name, price and duration")
    run(
        "INSERT INTO services (name, price, duration) VALUES (?, ?, ?)",
        (name, price, duration)
    )
    return jsonify(ok=True)


@app.post("/api/services/<int:service_id>")
@admin_required
def update_service(user, service_id):
    data = request.get_json(force=True)
    fields, values = [], []
    for key in ("name", "price", "duration", "active"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return jsonify(ok=False, error="No fields to update")
    values.append(service_id)
    run(
        f"UPDATE services SET {', '.join(fields)} WHERE service_id = ?",
        tuple(values)
    )
    return jsonify(ok=True)


# --- reports (admin only, café-focused) ---------------------------------

@app.get("/reports")
@admin_required
def reports_page(user):
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)

    today_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders WHERE DATE(order_date) = ?""",
        (today,), one=True, default={"order_count": 0, "total_sales": 0}
    )
    week_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders WHERE DATE(order_date) >= ?""",
        (week_ago,), one=True, default={"order_count": 0, "total_sales": 0}
    )
    top_sellers = query(
        """SELECT p.name,
                  SUM(i.quantity) AS qty,
                  SUM(i.quantity * i.price) AS revenue
             FROM order_items i
             JOIN orders   o ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) >= ?
            GROUP BY p.product_id, p.name
            ORDER BY qty DESC LIMIT 5""",
        (week_ago,)
    )
    daily = query(
        """SELECT DATE(order_date) AS day,
                  SUM(total_amount) AS total
             FROM orders
            WHERE DATE(order_date) >= ?
            GROUP BY DATE(order_date)
            ORDER BY day""",
        (week_ago,)
    )
    low_stock = query(
        "SELECT * FROM products "
        "WHERE stock <= ? AND status != 'hidden' "
        "ORDER BY stock ASC, name",
        (LOW_STOCK_LIMIT,)
    )
    upcoming = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date >= date('now', 'localtime')
              AND a.status = 'scheduled'
            ORDER BY a.appt_date, a.appt_time LIMIT 10"""
    )
    return render_template(
        "reports.html", user=user, active="reports",
        title="Reports", today_sales=today_sales, week_sales=week_sales,
        top_sellers=top_sellers, daily=daily, low_stock=low_stock,
        upcoming=upcoming, low_stock_limit=LOW_STOCK_LIMIT
    )


if __name__ == "__main__":
    app.run(debug=True)