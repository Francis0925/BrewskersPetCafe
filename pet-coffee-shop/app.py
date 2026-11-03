# Brewskers — main application.
# Dashboard, POS, inventory, appointments, services, reports, staff, profile.

import csv
import datetime
import decimal
import io
from functools import wraps

from flask import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
)

from activity import record_activity
from auth import (
    app,
    change_password,
    connect_db,
    create_user,
    hash_pw,
    list_users,
    make_default_password,
    set_user_active,
    set_user_role,
    verify_password,
)


# --- configuration -------------------------------------------------------

LOW_STOCK_LIMIT = 5
TAX_RATE = decimal.Decimal("0.08")
APPOINTMENT_STATUSES = ("scheduled", "completed", "cancelled")

ROLES = (
    "admin",
    "cashier",
    "inventory",
    "appointments",
    "viewer",
)

PERMISSIONS = {
    "admin": {"*"},
    "cashier": {
        "dashboard.read",
        "pos.use",
        "orders.read",
        "orders.reprint",
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

LANDING_PAGE = {
    "admin": "/dashboard",
    "cashier": "/pos",
    "inventory": "/inventory",
    "appointments": "/appointments",
    "viewer": "/dashboard",
}


# --- template helpers ----------------------------------------------------

app.jinja_env.globals["user_has"] = (
    lambda user, permission: (
        user is not None
        and (
            "*" in PERMISSIONS.get(user.get("role", ""), set())
            or permission in PERMISSIONS.get(user.get("role", ""), set())
        )
    )
)


# --- database utilities --------------------------------------------------

def clean(row):
    """Convert database values into JSON-friendly Python values."""
    result = dict(row)

    for key, value in list(result.items()):
        if isinstance(value, decimal.Decimal):
            result[key] = float(value)
        elif isinstance(value, datetime.timedelta):
            result[key] = str(value)[:-3].zfill(5)
        elif isinstance(value, datetime.date):
            result[key] = value.isoformat()

    return result


def query(sql, args=(), one=False, default=None):
    """Run a SELECT query and return all rows or one row."""
    db = connect_db()
    rows = [clean(row) for row in db.execute(sql, args).fetchall()]
    db.close()

    if one:
        return rows[0] if rows else default

    return rows


def run(sql, args=()):
    """Run an INSERT, UPDATE, or DELETE query and commit it."""
    db = connect_db()
    cursor = db.cursor()
    cursor.execute(sql, args)
    new_id = cursor.lastrowid
    db.commit()
    db.close()
    return new_id


# --- CSV utilities -------------------------------------------------------

def csv_download(filename, headers, rows):
    """Return records as a downloadable CSV file."""
    output = io.StringIO(newline="")

    writer = csv.writer(output)
    writer.writerow(headers)

    for row in rows:
        writer.writerow([
            row.get(header, "")
            for header in headers
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"'
        },
    )


def parse_csv_upload(upload, required_headers):
    """Parse an uploaded CSV and verify its headers."""
    if upload is None:
        raise ValueError("Choose a CSV file")

    filename = (upload.filename or "").lower()

    if not filename.endswith(".csv"):
        raise ValueError("Only CSV files are allowed")

    raw = upload.read()

    if not raw:
        raise ValueError("The CSV file is empty")

    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(
            "The CSV must use UTF-8 encoding"
        )

    reader = csv.DictReader(io.StringIO(content))

    if not reader.fieldnames:
        raise ValueError("The CSV file is empty")

    headers = {
        header.strip().lower(): header
        for header in reader.fieldnames
        if header is not None
    }

    missing = [
        header
        for header in required_headers
        if header not in headers
    ]

    if missing:
        raise ValueError(
            "Missing required column(s): "
            + ", ".join(missing)
        )

    return reader, headers


def csv_value(row, headers, key, default=""):
    """Read one normalized field from a CSV row."""
    original_header = headers.get(key)

    if original_header is None:
        return default

    value = row.get(original_header)

    if value is None:
        return default

    return str(value).strip()


def parse_active(value, default=True):
    """Convert a CSV active value into a SQLite integer."""
    value = str(value).strip().lower()

    if value == "":
        return 1 if default else 0

    if value in {"1", "true", "yes", "on", "active"}:
        return 1

    if value in {"0", "false", "no", "off", "inactive"}:
        return 0

    raise ValueError(
        "Active must be 1, 0, true, false, yes, or no"
    )


def validate_product_csv_row(row, headers):
    """Validate and normalize one product CSV row."""
    name = csv_value(row, headers, "name")
    category = csv_value(row, headers, "category")
    price_text = csv_value(row, headers, "price")
    stock_text = csv_value(row, headers, "stock")

    if not name:
        raise ValueError("Name is required")

    if not category:
        raise ValueError("Category is required")

    try:
        price = float(price_text)
    except (TypeError, ValueError):
        raise ValueError("Price must be a valid number")

    try:
        stock = int(stock_text or "0")
    except (TypeError, ValueError):
        raise ValueError("Stock must be a whole number")

    if price < 0:
        raise ValueError("Price cannot be negative")

    if stock < 0:
        raise ValueError("Stock cannot be negative")

    return {
        "name": name,
        "category": category,
        "price": price,
        "stock": stock,
    }


def validate_service_csv_row(row, headers):
    """Validate and normalize one service CSV row."""
    name = csv_value(row, headers, "name")
    price_text = csv_value(row, headers, "price")
    duration_text = csv_value(row, headers, "duration")
    active_text = csv_value(
        row,
        headers,
        "active",
        "1",
    )

    if not name:
        raise ValueError("Name is required")

    try:
        price = float(price_text)
    except (TypeError, ValueError):
        raise ValueError("Price must be a valid number")

    try:
        duration = int(duration_text)
    except (TypeError, ValueError):
        raise ValueError(
            "Duration must be a whole number"
        )

    if price < 0:
        raise ValueError("Price cannot be negative")

    if duration <= 0:
        raise ValueError(
            "Duration must be greater than zero"
        )

    try:
        active = parse_active(active_text)
    except ValueError as error:
        raise ValueError(str(error))

    return {
        "name": name,
        "price": price,
        "duration": duration,
        "active": active,
    }


# --- session and permissions ---------------------------------------------

def current_user():
    """Return the logged-in user when the session cookie is valid."""
    token = request.cookies.get("session")

    if not token:
        return None

    db = connect_db()
    row = db.execute(
        """SELECT u.user_id, u.username, u.email, u.role,
                  u.must_change_password
             FROM users u
             JOIN (
                 SELECT user_id, token, expires_at FROM sessions
                 UNION
                 SELECT user_id, token, expires_at FROM remember_tokens
             ) token_record ON token_record.user_id = u.user_id
            WHERE token_record.token = ?
              AND token_record.expires_at > datetime('now', 'localtime')
              AND u.deactivated_at IS NULL""",
        (token,),
    ).fetchone()
    db.close()

    if not row:
        return None

    return dict(row)


def user_has(user, permission):
    """Return whether the user's role includes the requested permission."""
    if not user:
        return False

    permissions = PERMISSIONS.get(user.get("role", ""), set())
    return "*" in permissions or permission in permissions


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()

        if not user:
            if request.path.startswith("/api/"):
                return jsonify(
                    ok=False,
                    error="Please log in",
                ), 401
            return redirect("/")

        return view(user, *args, **kwargs)

    return wrapper


def require(permission):
    """Require a logged-in account with the requested permission."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()

            if not user:
                if request.path.startswith("/api/"):
                    return jsonify(
                        ok=False,
                        error="Please log in",
                    ), 401
                return redirect("/")

            if user["must_change_password"] and not request.path.startswith(
                (
                    "/first-login",
                    "/api/profile/change-password",
                    "/logout",
                    "/static",
                )
            ):
                return redirect("/first-login")

            if not user_has(user, permission):
                if request.path.startswith("/api/"):
                    return jsonify(
                        ok=False,
                        error="Not allowed",
                    ), 403
                return redirect("/dashboard")

            return view(user, *args, **kwargs)

        return wrapper

    return decorator


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()

        if not user or user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify(
                    ok=False,
                    error="Admins only",
                ), 403
            return redirect("/dashboard")

        return view(user, *args, **kwargs)

    return wrapper


# --- shared sidebar information ------------------------------------------

@app.context_processor
def sidebar_summary():
    """Provide compact daily information for the sidebar footer."""
    if request.path.startswith("/api/"):
        return {"sidebar_summary": None}

    user = current_user()

    if not user:
        return {"sidebar_summary": None}

    today = datetime.date.today()

    sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) = ?""",
        (today,),
        one=True,
        default={
            "order_count": 0,
            "total_sales": 0,
        },
    )

    appointment_count = query(
        """SELECT COUNT(*) AS n
             FROM appointments
            WHERE appt_date = ?
              AND status = 'scheduled'""",
        (today,),
        one=True,
        default={"n": 0},
    )["n"]

    low_stock_count = query(
        """SELECT COUNT(*) AS n
             FROM products
            WHERE stock <= ?
              AND status != 'hidden'""",
        (LOW_STOCK_LIMIT,),
        one=True,
        default={"n": 0},
    )["n"]

    return {
        "sidebar_summary": {
            "order_count": sales["order_count"],
            "total_sales": sales["total_sales"],
            "appointment_count": appointment_count,
            "low_stock_count": low_stock_count,
        }
    }


# --- logout --------------------------------------------------------------

@app.get("/logout")
def logout():
    token = request.cookies.get("session")

    if token:
        db = connect_db()
        db.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,),
        )
        db.execute(
            "DELETE FROM remember_tokens WHERE token = ?",
            (token,),
        )
        db.commit()
        db.close()

    response = redirect("/")
    response.delete_cookie("session")
    return response


# --- first login and password changes ------------------------------------

@app.get("/first-login")
def first_login_page():
    user = current_user()

    if not user:
        return redirect("/")

    if not user["must_change_password"]:
        return redirect("/dashboard")

    return render_template(
        "first_login.html",
        user=user,
        title="Set your password",
    )


@app.post("/api/profile/change-password")
@login_required
def api_change_password(user):
    user = current_user()
    data = request.get_json(force=True) or {}

    new_password = data.get("new_password") or ""
    confirm = data.get("confirm") or ""

    if len(new_password) < 8:
        return jsonify(
            ok=False,
            error="Password must be at least 8 characters",
        ), 400

    if new_password != confirm:
        return jsonify(
            ok=False,
            error="Passwords do not match",
        ), 400

    db = connect_db()
    account = db.execute(
        "SELECT password FROM users WHERE user_id = ?",
        (user["user_id"],),
    ).fetchone()
    db.close()

    if not account:
        return jsonify(
            ok=False,
            error="User not found",
        ), 404

    if user["must_change_password"]:
        temporary_password = data.get("temporary_password") or ""

        if not temporary_password:
            return jsonify(
                ok=False,
                error="Temporary password is required",
            ), 400

        if not verify_password(
            account["password"],
            temporary_password,
        ):
            return jsonify(
                ok=False,
                error="Temporary password is incorrect",
            ), 403
    else:
        current_password = data.get("current_password") or ""

        if not current_password:
            return jsonify(
                ok=False,
                error="Current password is required",
            ), 400

        if not verify_password(
            account["password"],
            current_password,
        ):
            return jsonify(
                ok=False,
                error="Current password is incorrect",
            ), 403

    change_password(user["user_id"], new_password)

    return jsonify(ok=True)


# --- role-based landing --------------------------------------------------

@app.get("/landing")
def landing():
    user = current_user()

    if not user:
        return redirect("/")

    if user["must_change_password"]:
        return redirect("/first-login")

    return redirect(
        LANDING_PAGE.get(user["role"], "/dashboard")
    )


# --- profile -------------------------------------------------------------

@app.get("/profile")
@login_required
def profile_page(user):
    full_account = query(
        """
        SELECT
            user_id,
            username,
            email,
            role,
            created_at,
            last_login_at
        FROM users
        WHERE user_id = ?
        """,
        (user["user_id"],),
        one=True,
    )

    account = full_account or user

    def format_date(value, fallback):
        """Convert a stored timestamp into a readable date."""
        if not value:
            return fallback

        try:
            parsed = datetime.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return str(value)

        return parsed.strftime("%b %d, %Y")

    def format_login_date(value):
        """Format the last-login date and time."""
        if not value:
            return "First session"

        try:
            parsed = datetime.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return str(value)

        formatted_time = parsed.strftime("%I:%M %p").lstrip("0")

        return f"{parsed.strftime('%b')} {parsed.day}, {parsed:%Y} · {formatted_time}"

    last_login_display = format_login_date(account["last_login_at"])
    created_at_display = format_date(account["created_at"], "—")

    return render_template(
        "profile.html",
        user=account,
        last_login_display=last_login_display,
        created_at_display=created_at_display,
        title="My profile & security",
        active="profile",
    )


# --- administration ------------------------------------------------------

@app.get("/admin")
@admin_required
def admin_page(user):
    """Display the unified administration page."""
    staff = list_users()

    activity = query(
        """SELECT a.*, u.username AS actor_name
             FROM activity_log a
             LEFT JOIN users u ON u.user_id = a.user_id
            ORDER BY a.activity_id DESC
            LIMIT 20"""
    )

    active_staff_count = sum(
        1 for account in staff if not account["deactivated_at"]
    )

    return render_template(
        "admin.html",
        user=user,
        active="admin",
        title="Administration",
        staff=staff,
        active_staff_count=active_staff_count,
        activity=activity,
    )


@app.get("/admin/staff")
@admin_required
def admin_staff_page(user):
    rows = list_users()

    staff = [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "must_change_password": bool(
                row["must_change_password"]
            ),
            "deactivated_at": row["deactivated_at"],
            "created_at": row["created_at"],
            "last_login_at": row["last_login_at"],
        }
        for row in rows
    ]

    return render_template(
        "admin_staff.html",
        user=user,
        active="admin",
        title="Staff",
        staff=staff,
        roles=ROLES,
    )


@app.post("/api/admin/staff")
@admin_required
def api_admin_create_staff(user):
    data = request.get_json(force=True) or {}

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    role = (data.get("role") or "cashier").strip()
    phrase = (data.get("phrase") or username).strip()

    if not username or not email:
        return jsonify(
            ok=False,
            error="Username and email are required",
        ), 400

    if role not in ROLES or role == "admin":
        return jsonify(
            ok=False,
            error="Invalid role",
        ), 400

    if "@" not in email or "." not in email:
        return jsonify(
            ok=False,
            error="Invalid email",
        ), 400

    temporary_password = make_default_password(phrase)

    new_id = create_user(
        username=username,
        email=email,
        password=temporary_password,
        role=role,
        created_by=user["user_id"],
        must_change_password=True,
    )

    if not new_id:
        return jsonify(
            ok=False,
            error="Username or email already exists",
        ), 409

    record_activity(
        user_id=user["user_id"],
        action="staff_created",
        description=f"Created staff account for {username}",
        entity_type="user",
        entity_id=new_id,
    )

    return jsonify(
        ok=True,
        temp_password=temporary_password,
        user_id=new_id,
    )


@app.post("/api/admin/staff/<int:user_id>/role")
@admin_required
def api_admin_set_role(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(
            ok=False,
            error="You can't change your own role",
        ), 400

    data = request.get_json(force=True) or {}
    role = (data.get("role") or "").strip()

    if role not in ROLES or role == "admin":
        return jsonify(
            ok=False,
            error="Invalid role",
        ), 400

    account = query(
        "SELECT username FROM users WHERE user_id = ?",
        (user_id,),
        one=True,
    )

    if not account:
        return jsonify(
            ok=False,
            error="User not found",
        ), 404

    set_user_role(user_id, role)

    record_activity(
        user_id=user["user_id"],
        action="role_changed",
        description=(
            f"Changed {account['username']}'s role to {role}"
        ),
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/toggle-active")
@admin_required
def api_admin_toggle_active(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(
            ok=False,
            error="You can't deactivate yourself",
        ), 400

    data = request.get_json(force=True) or {}
    active = bool(data.get("active", True))

    account = query(
        "SELECT username FROM users WHERE user_id = ?",
        (user_id,),
        one=True,
    )

    if not account:
        return jsonify(
            ok=False,
            error="User not found",
        ), 404

    set_user_active(user_id, active)

    status_text = "Activated" if active else "Deactivated"

    record_activity(
        user_id=user["user_id"],
        action="staff_status_changed",
        description=(
            f"{status_text} staff account {account['username']}"
        ),
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/reset-password")
@admin_required
def api_admin_reset_password(user, user_id):
    data = request.get_json(force=True) or {}
    phrase = (data.get("phrase") or "").strip()

    account = query(
        "SELECT username FROM users WHERE user_id = ?",
        (user_id,),
        one=True,
    )

    if not account:
        return jsonify(
            ok=False,
            error="User not found",
        ), 404

    seed_phrase = phrase or account["username"]
    temporary_password = make_default_password(seed_phrase)

    db = connect_db()
    db.execute(
        "UPDATE users "
        "SET password = ?, must_change_password = 1 "
        "WHERE user_id = ?",
        (
            hash_pw(temporary_password),
            user_id,
        ),
    )
    db.execute(
        "DELETE FROM sessions WHERE user_id = ?",
        (user_id,),
    )
    db.execute(
        "DELETE FROM remember_tokens WHERE user_id = ?",
        (user_id,),
    )
    db.commit()
    db.close()

    record_activity(
        user_id=user["user_id"],
        action="password_reset",
        description=(
            f"Reset the password for {account['username']}"
        ),
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(
        ok=True,
        temp_password=temporary_password,
    )


# --- dashboard -----------------------------------------------------------

@app.get("/dashboard")
@require("dashboard.read")
def dashboard(user):
    today = datetime.date.today()

    todays_appointments = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date = ?
              AND a.status != 'cancelled'
            ORDER BY a.appt_time""",
        (today,),
    )

    sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) = ?""",
        (today,),
        one=True,
        default={
            "order_count": 0,
            "total_sales": 0,
        },
    )

    low_stock_count = query(
        "SELECT COUNT(*) AS n FROM products "
        "WHERE stock <= ? AND status != 'hidden'",
        (LOW_STOCK_LIMIT,),
        one=True,
        default={"n": 0},
    )["n"]

    top_seller = query(
        """SELECT p.name
             FROM order_items i
             JOIN orders o ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) = ?
            GROUP BY p.product_id, p.name
            ORDER BY SUM(i.quantity) DESC
            LIMIT 1""",
        (today,),
        one=True,
    )

    recent_orders = query(
        """SELECT o.order_id,
                  o.order_no,
                  o.customer_name,
                  o.total_amount,
                  o.payment_method,
                  o.order_date
             FROM orders o
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT 5"""
    )

    average_ticket = (
        sales["total_sales"] / sales["order_count"]
        if sales["order_count"]
        else 0
    )

    return render_template(
        "dashboard.html",
        user=user,
        active="dashboard",
        title="Dashboard",
        today=today,
        appointments=todays_appointments,
        sales=sales,
        low_stock_count=low_stock_count,
        top_seller=top_seller["name"] if top_seller else "-",
        average_ticket=average_ticket,
        recent_orders=recent_orders,
    )


# --- point of sale -------------------------------------------------------

@app.get("/pos")
@require("pos.use")
def pos(user):
    products = query(
        "SELECT * FROM products "
        "WHERE status = 'available' AND stock > 0 "
        "ORDER BY category, name"
    )

    return render_template(
        "pos.html",
        user=user,
        active="pos",
        title="Point of sale",
        products=products,
    )


@app.get("/orders")
@require("orders.read")
def order_history(user):
    """Display the most recent cafe orders."""
    recent_orders = query(
        """SELECT o.*, u.username AS cashier_name
             FROM orders o
             LEFT JOIN users u ON u.user_id = o.created_by
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT 100"""
    )

    return render_template(
        "order_history.html",
        user=user,
        active="orders",
        title="Recent orders",
        orders=recent_orders,
    )


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
        return jsonify(
            ok=False,
            error="Order not found",
        ), 404

    items = query(
        """SELECT oi.product_id,
                  oi.quantity,
                  oi.price,
                  COALESCE(p.name, 'Removed product') AS name
             FROM order_items oi
             LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.item_id""",
        (order_id,),
    )

    subtotal = round(
        sum(
            float(item["price"]) * int(item["quantity"])
            for item in items
        ),
        2,
    )

    tax = round(
        float(order["total_amount"]) - subtotal,
        2,
    )

    return jsonify(
        ok=True,
        receipt={
            "order_id": order["order_id"],
            "order_no": order["order_no"],
            "customer_name": order["customer_name"] or "Walk-in",
            "order_date": order["order_date"],
            "cashier_name": (
                order["cashier_name"] or "Unknown cashier"
            ),
            "payment_method": order["payment_method"],
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
                    "line_total": round(
                        float(item["price"])
                        * int(item["quantity"]),
                        2,
                    ),
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
        return jsonify(
            ok=False,
            error="The cart is empty",
        ), 400

    method = data.get("payment_method", "cash")

    if method not in ("cash", "gcash", "card"):
        return jsonify(
            ok=False,
            error="Unknown payment method",
        ), 400

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
                return jsonify(
                    ok=False,
                    error="Invalid cart item",
                ), 400

            if product_id < 1 or quantity < 1:
                return jsonify(
                    ok=False,
                    error="Invalid cart quantity",
                ), 400

            cursor.execute(
                "SELECT * FROM products WHERE product_id = ?",
                (product_id,),
            )
            product = cursor.fetchone()

            if not product or product["status"] != "available":
                return jsonify(
                    ok=False,
                    error="A product in the cart is unavailable",
                ), 400

            if product["stock"] < quantity:
                return jsonify(
                    ok=False,
                    error=f"Not enough stock for {product['name']}",
                ), 409

            price = decimal.Decimal(str(product["price"]))
            subtotal += price * quantity
            order_lines.append(
                (
                    product["product_id"],
                    product["name"],
                    quantity,
                    price,
                )
            )

        subtotal = subtotal.quantize(
            cents,
            rounding=decimal.ROUND_HALF_UP,
        )

        order_total = (
            subtotal * (1 + TAX_RATE)
        ).quantize(
            cents,
            rounding=decimal.ROUND_HALF_UP,
        )

        tax = order_total - subtotal

        if method == "cash":
            try:
                amount_paid = decimal.Decimal(
                    str(data.get("amount_paid") or 0)
                ).quantize(
                    cents,
                    rounding=decimal.ROUND_HALF_UP,
                )
            except decimal.InvalidOperation:
                return jsonify(
                    ok=False,
                    error="Enter a valid cash amount",
                ), 400

            if amount_paid < order_total:
                return jsonify(
                    ok=False,
                    error="Amount tendered is less than the total",
                ), 400
        else:
            amount_paid = order_total

        change = amount_paid - order_total

        order_no = (
            "ORD-"
            + datetime.datetime.now().strftime(
                "%y%m%d%H%M%S%f"
            )[:14]
        )

        cursor.execute(
            """INSERT INTO orders
                 (order_no, customer_name, total_amount,
                  payment_method, amount_paid, change_amount, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order_no,
                (
                    data.get("customer_name") or "Walk-in"
                ).strip() or "Walk-in",
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
                "INSERT INTO order_items "
                "(order_id, product_id, quantity, price) "
                "VALUES (?, ?, ?, ?)",
                (
                    order_id,
                    product_id,
                    quantity,
                    float(price),
                ),
            )

            cursor.execute(
                """UPDATE products
                      SET stock = stock - ?
                    WHERE product_id = ?
                      AND stock >= ?""",
                (
                    quantity,
                    product_id,
                    quantity,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Product stock changed during checkout"
                )

        db.commit()

        return jsonify(
            ok=True,
            order_no=order_no,
            method=method,
            subtotal=float(subtotal),
            tax=float(tax),
            total=float(order_total),
            paid=float(amount_paid),
            change=float(change),
            lines=[
                {
                    "name": name,
                    "qty": quantity,
                    "price": float(price),
                }
                for _id, name, quantity, price in order_lines
            ],
        )
    except Exception:
        db.rollback()
        app.logger.exception("Could not create order")
        return jsonify(
            ok=False,
            error="Could not save the order. Please try again.",
        ), 500
    finally:
        db.close()


# --- inventory -----------------------------------------------------------

@app.get("/inventory")
@require("inventory.read")
def inventory(user):
    products = query(
        "SELECT * FROM products "
        "WHERE status != 'hidden' "
        "ORDER BY category, name"
    )

    return render_template(
        "inventory.html",
        user=user,
        active="inventory",
        title="Inventory",
        products=products,
        low_stock_limit=LOW_STOCK_LIMIT,
    )


@app.post("/api/products")
@require("inventory.write")
def add_product(user):
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()

    try:
        price = float(data.get("price"))
        stock = int(data.get("stock") or 0)
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error="Price and stock must be numbers",
        ), 400

    if (
        not name
        or not category
        or price < 0
        or stock < 0
    ):
        return jsonify(
            ok=False,
            error="Fill in name, category, price and stock",
        ), 400

    run(
        "INSERT INTO products "
        "(category, name, price, stock) "
        "VALUES (?, ?, ?, ?)",
        (
            category,
            name,
            price,
            stock,
        ),
    )

    return jsonify(ok=True)


@app.post("/api/products/<int:product_id>/stock")
@require("inventory.write")
def set_stock(user, product_id):
    data = request.get_json(force=True) or {}
    amount = data.get("stock")

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error="Stock must be a whole number",
        ), 400

    if amount < 0:
        return jsonify(
            ok=False,
            error="Stock cannot be negative",
        ), 400

    if data.get("restock"):
        run(
            "UPDATE products "
            "SET stock = stock + ? "
            "WHERE product_id = ?",
            (
                amount,
                product_id,
            ),
        )
    else:
        run(
            "UPDATE products "
            "SET stock = ? "
            "WHERE product_id = ?",
            (
                amount,
                product_id,
            ),
        )

    return jsonify(ok=True)


@app.delete("/api/products/<int:product_id>")
@require("inventory.write")
def remove_product(user, product_id):
    run(
        "UPDATE products SET status = 'hidden' WHERE product_id = ?",
        (product_id,),
    )
    return jsonify(ok=True)


# --- appointments and schedule ------------------------------------------

APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name
                        FROM appointments a
                        JOIN services s ON s.service_id = a.service_id
                        {where}
                       ORDER BY a.appt_date, a.appt_time"""


@app.get("/appointments")
@require("appointments.read")
def appointments(user):
    upcoming = query(
        APPOINTMENT_SQL.format(
            where=(
                "WHERE a.appt_date >= date('now', 'localtime') "
                "AND a.status = 'scheduled'"
            )
        )
    )

    return render_template(
        "appointments.html",
        user=user,
        active="appointments",
        title="Appointments",
        appointments=upcoming,
        services=query(
            "SELECT * FROM services "
            "WHERE active = 1 "
            "ORDER BY name"
        ),
        today=datetime.date.today(),
    )


@app.get("/schedule")
@require("appointments.read")
def schedule(user):
    appointments_list = query(
        APPOINTMENT_SQL.format(
            where="WHERE a.status != 'cancelled'"
        )
    )

    return render_template(
        "schedule.html",
        user=user,
        active="schedule",
        title="Schedule",
        appointments=appointments_list,
        services=query(
            "SELECT * FROM services "
            "WHERE active = 1 "
            "ORDER BY name"
        ),
        today=datetime.date.today(),
    )


@app.post("/api/appointments")
@require("appointments.write")
def add_appointment(user):
    data = request.get_json(force=True) or {}

    required_fields = (
        "pet_name",
        "owner_name",
        "phone",
        "service_id",
        "appt_date",
        "appt_time",
    )

    if not all(
        str(data.get(field) or "").strip()
        for field in required_fields
    ):
        return jsonify(
            ok=False,
            error="Please fill in every required field",
        ), 400

    run(
        """INSERT INTO appointments
             (pet_name, pet_type, breed, pet_age, owner_name, phone,
              service_id, appt_date, appt_time, notes, photo, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["pet_name"].strip(),
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
            user["user_id"],
        ),
    )

    return jsonify(ok=True)


@app.post("/api/appointments/<int:appointment_id>/status")
@require("appointments.write")
def set_appointment_status(user, appointment_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")

    if status not in APPOINTMENT_STATUSES:
        return jsonify(
            ok=False,
            error="Unknown status",
        ), 400

    run(
        "UPDATE appointments SET status = ? WHERE appointment_id = ?",
        (
            status,
            appointment_id,
        ),
    )

    return jsonify(ok=True)


# --- services ------------------------------------------------------------

@app.get("/services")
@require("services.read")
def services_page(user):
    services = query(
        "SELECT * FROM services ORDER BY name"
    )

    return render_template(
        "services.html",
        user=user,
        active="services",
        title="Services",
        services=services,
    )


@app.post("/api/services")
@admin_required
def add_service(user):
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()

    try:
        price = float(data.get("price"))
        duration = int(data.get("duration") or 30)
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error="Price and duration must be numbers",
        ), 400

    if not name or price < 0 or duration <= 0:
        return jsonify(
            ok=False,
            error="Fill in name, price and duration",
        ), 400

    run(
        "INSERT INTO services (name, price, duration) "
        "VALUES (?, ?, ?)",
        (
            name,
            price,
            duration,
        ),
    )

    return jsonify(ok=True)


@app.post("/api/services/<int:service_id>")
@admin_required
def update_service(user, service_id):
    data = request.get_json(force=True) or {}
    fields = []
    values = []

    for key in ("name", "price", "duration", "active"):
        if key not in data:
            continue

        if key == "name":
            value = (data.get("name") or "").strip()

            if not value:
                return jsonify(
                    ok=False,
                    error="Service name is required",
                ), 400
        elif key == "price":
            try:
                value = float(data.get("price"))
            except (TypeError, ValueError):
                return jsonify(
                    ok=False,
                    error="Price must be a number",
                ), 400

            if value < 0:
                return jsonify(
                    ok=False,
                    error="Price cannot be negative",
                ), 400
        elif key == "duration":
            try:
                value = int(data.get("duration"))
            except (TypeError, ValueError):
                return jsonify(
                    ok=False,
                    error="Duration must be a number",
                ), 400

            if value <= 0:
                return jsonify(
                    ok=False,
                    error="Duration must be greater than zero",
                ), 400
        else:
            value = 1 if bool(data.get("active")) else 0

        fields.append(f"{key} = ?")
        values.append(value)

    if not fields:
        return jsonify(
            ok=False,
            error="No fields to update",
        ), 400

    values.append(service_id)

    run(
        f"UPDATE services SET {', '.join(fields)} "
        "WHERE service_id = ?",
        tuple(values),
    )

    return jsonify(ok=True)


# --- reports -------------------------------------------------------------

@app.get("/reports")
@admin_required
def reports_page(user):
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)

    today_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) = ?""",
        (today,),
        one=True,
        default={
            "order_count": 0,
            "total_sales": 0,
        },
    )

    week_sales = query(
        """SELECT COUNT(*) AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_sales
             FROM orders
            WHERE DATE(order_date) >= ?""",
        (week_ago,),
        one=True,
        default={
            "order_count": 0,
            "total_sales": 0,
        },
    )

    top_sellers = query(
        """SELECT p.name,
                  SUM(i.quantity) AS qty,
                  SUM(i.quantity * i.price) AS revenue
             FROM order_items i
             JOIN orders o ON o.order_id = i.order_id
             JOIN products p ON p.product_id = i.product_id
            WHERE DATE(o.order_date) >= ?
            GROUP BY p.product_id, p.name
            ORDER BY qty DESC
            LIMIT 5""",
        (week_ago,),
    )

    daily = query(
        """SELECT DATE(order_date) AS day,
                  SUM(total_amount) AS total
             FROM orders
            WHERE DATE(order_date) >= ?
            GROUP BY DATE(order_date)
            ORDER BY day""",
        (week_ago,),
    )

    low_stock = query(
        "SELECT * FROM products "
        "WHERE stock <= ? AND status != 'hidden' "
        "ORDER BY stock ASC, name",
        (LOW_STOCK_LIMIT,),
    )

    upcoming = query(
        """SELECT a.*, s.name AS service_name
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date >= date('now', 'localtime')
              AND a.status = 'scheduled'
            ORDER BY a.appt_date, a.appt_time
            LIMIT 10"""
    )

    return render_template(
        "reports.html",
        user=user,
        active="reports",
        title="Reports",
        today_sales=today_sales,
        week_sales=week_sales,
        top_sellers=top_sellers,
        daily=daily,
        low_stock=low_stock,
        upcoming=upcoming,
        low_stock_limit=LOW_STOCK_LIMIT,
    )


# --- CSV import and export ----------------------------------------------

# --- CSV import and export ----------------------------------------------

@app.get("/admin/data")
@admin_required
def admin_data(user):
    """Display the CSV import and export tools."""
    return render_template(
        "data_tools.html",
        title="Import & export",
        active="admin",
        user=user,
        exports={
            "products": "Products",
            "services": "Services",
        },
    )


@app.get("/api/admin/export/<export_type>")
@admin_required
def export_admin_data(user, export_type):
    """Export products or services as a CSV download."""
    if export_type == "products":
        products = query(
            """
            SELECT category, name, price, stock
              FROM products
             WHERE status != 'hidden'
             ORDER BY category, name
            """
        )

        response = csv_download(
            "brewskers-products.csv",
            ["name", "category", "price", "stock"],
            products,
        )

        record_activity(
            user_id=user["user_id"],
            action="products_exported",
            description=(
                f"Exported {len(products)} products to CSV"
            ),
            entity_type="product",
        )

        return response

    if export_type == "services":
        services = query(
            """
            SELECT name, price, duration, active
              FROM services
             ORDER BY name
            """
        )

        response = csv_download(
            "brewskers-services.csv",
            ["name", "price", "duration", "active"],
            services,
        )

        record_activity(
            user_id=user["user_id"],
            action="services_exported",
            description=(
                f"Exported {len(services)} services to CSV"
            ),
            entity_type="service",
        )

        return response

    return jsonify(
        ok=False,
        error="Unknown export type",
    ), 404


@app.post("/api/admin/import/preview")
@admin_required
def preview_admin_import(user):
    """Validate an uploaded CSV without changing the database."""
    entity_type = (
        request.form.get("entity_type", "")
        .strip()
        .lower()
    )

    if entity_type not in {"products", "services"}:
        return jsonify(
            ok=False,
            error="Invalid record type",
        ), 400

    upload = request.files.get("file")

    try:
        if entity_type == "products":
            reader, headers = parse_csv_upload(
                upload,
                ["name", "category", "price", "stock"],
            )
            validator = validate_product_csv_row
        else:
            reader, headers = parse_csv_upload(
                upload,
                ["name", "price", "duration", "active"],
            )
            validator = validate_service_csv_row

        valid_count = 0
        errors = []

        for row_number, row in enumerate(reader, start=2):
            try:
                validator(row, headers)
                valid_count += 1
            except ValueError as error:
                errors.append({
                    "row": row_number,
                    "message": str(error),
                })

        return jsonify(
            ok=True,
            entity_type=entity_type,
            valid_count=valid_count,
            error_count=len(errors),
            errors=errors,
        )
    except ValueError as error:
        return jsonify(
            ok=False,
            error=str(error),
        ), 400


@app.post("/api/admin/import/confirm")
@admin_required
def confirm_admin_import(user):
    """Validate and import records from an uploaded CSV."""
    entity_type = (
        request.form.get("entity_type", "")
        .strip()
        .lower()
    )

    if entity_type not in {"products", "services"}:
        return jsonify(
            ok=False,
            error="Invalid record type",
        ), 400

    upload = request.files.get("file")

    try:
        if entity_type == "products":
            reader, headers = parse_csv_upload(
                upload,
                ["name", "category", "price", "stock"],
            )
            validator = validate_product_csv_row
        else:
            reader, headers = parse_csv_upload(
                upload,
                ["name", "price", "duration", "active"],
            )
            validator = validate_service_csv_row

        rows = [
            validator(row, headers)
            for row in reader
        ]

        if not rows:
            raise ValueError(
                "The CSV contains no data rows"
            )

    except ValueError as error:
        return jsonify(
            ok=False,
            error=str(error),
        ), 400

    db = connect_db()
    cursor = db.cursor()

    try:
        if entity_type == "products":
            for item in rows:
                existing = cursor.execute(
                    """
                    SELECT product_id
                      FROM products
                     WHERE name = ?
                     ORDER BY product_id
                     LIMIT 1
                    """,
                    (item["name"],),
                ).fetchone()

                if existing:
                    cursor.execute(
                        """
                        UPDATE products
                           SET category = ?,
                               price = ?,
                               stock = ?,
                               status = 'available'
                         WHERE product_id = ?
                        """,
                        (
                            item["category"],
                            item["price"],
                            item["stock"],
                            existing["product_id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO products
                             (category, name, price, stock, status)
                        VALUES (?, ?, ?, ?, 'available')
                        """,
                        (
                            item["category"],
                            item["name"],
                            item["price"],
                            item["stock"],
                        ),
                    )
        else:
            for item in rows:
                existing = cursor.execute(
                    """
                    SELECT service_id
                      FROM services
                     WHERE name = ?
                     ORDER BY service_id
                     LIMIT 1
                    """,
                    (item["name"],),
                ).fetchone()

                if existing:
                    cursor.execute(
                        """
                        UPDATE services
                           SET price = ?,
                               duration = ?,
                               active = ?
                         WHERE service_id = ?
                        """,
                        (
                            item["price"],
                            item["duration"],
                            item["active"],
                            existing["service_id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO services
                             (name, price, duration, active)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            item["name"],
                            item["price"],
                            item["duration"],
                            item["active"],
                        ),
                    )

        db.commit()

    except Exception:
        db.rollback()

        app.logger.exception(
            "CSV import failed"
        )

        return jsonify(
            ok=False,
            error="Could not import the CSV",
        ), 500
    finally:
        db.close()

    record_activity(
        user_id=user["user_id"],
        action="csv_imported",
        description=(
            f"Imported {len(rows)} {entity_type} from CSV"
        ),
        entity_type=entity_type,
    )

    return jsonify(
        ok=True,
        imported_count=len(rows),
    )


@app.post("/api/admin/reset-data")
@admin_required
def api_admin_reset_data(user):
    """Clear selected business data while preserving staff accounts."""
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip()

    confirmation = (
        data.get("confirmation") or ""
    ).strip().upper()

    if confirmation != "DELETE":
        return jsonify(
            ok=False,
            error="Type DELETE to confirm",
        ), 400

    descriptions = {
        "reset_stock": "Reset all product stock to zero",
        "hide_products": "Hid all products from inventory and the POS",
        "hide_services": "Hid all services from booking",
        "delete_appointments": "Deleted all appointments",
        "delete_orders": "Deleted all order and receipt history",
    }

    if action not in descriptions:
        return jsonify(
            ok=False,
            error="Unknown reset action",
        ), 400

    db = connect_db()
    cursor = db.cursor()

    try:
        if action == "reset_stock":
            cursor.execute(
                "UPDATE products SET stock = 0"
            )

        elif action == "hide_products":
            cursor.execute(
                "UPDATE products SET status = 'hidden'"
            )

        elif action == "hide_services":
            cursor.execute(
                "UPDATE services SET active = 0"
            )

        elif action == "delete_appointments":
            cursor.execute(
                "DELETE FROM appointments"
            )

        elif action == "delete_orders":
            cursor.execute(
                "DELETE FROM order_items"
            )
            cursor.execute(
                "DELETE FROM orders"
            )

        db.commit()

    except Exception:
        db.rollback()

        app.logger.exception(
            "Admin data reset failed"
        )

        return jsonify(
            ok=False,
            error="Could not clear the selected data",
        ), 500
    finally:
        db.close()

    record_activity(
        user_id=user["user_id"],
        action="data_cleared",
        description=descriptions[action],
        entity_type="system",
    )

    return jsonify(
        ok=True,
        message=descriptions[action],
    )


if __name__ == "__main__":
    app.run(debug=True)