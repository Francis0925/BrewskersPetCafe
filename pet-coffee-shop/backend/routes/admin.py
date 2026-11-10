# Brewskers administration routes
# Admin dashboard, staff management and password resets

import datetime

from flask import jsonify, render_template, request

from backend.activity import record_activity
from backend.auth import (
    app,
    connect_db,
    create_user,
    hash_pw,
    list_users,
    make_default_password,
    set_user_active,
    set_user_role,
)
from backend.config import ROLES
from backend.helpers import query
from backend.permissions import admin_required
from backend.settings import get_store_settings

# Groups activity log entries so the feed can show a small colored badge.
ACTIVITY_CATEGORIES = {
    "staff_created": "staff",
    "role_changed": "staff",
    "staff_status_changed": "staff",
    "password_reset": "staff",
    "csv_imported": "data",
    "all_imported": "data",
    "database_restored": "data",
    "all_exported": "data",
    "all_sql_exported": "data",
    "all_db_exported": "data",
    "products_exported": "data",
    "services_exported": "data",
    "orders_exported": "data",
    "appointments_exported": "data",
    "order_status_changed": "orders",
    "backup_created": "system",
    "backup_restored": "data",
    "backup_deleted": "system",
    "settings_updated": "system",
    "data_cleared": "clear",
}


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

    for event in activity:
        event["category"] = ACTIVITY_CATEGORIES.get(event["action"], "system")

    active_staff_count = sum(1 for account in staff if not account["deactivated_at"])

    today = datetime.date.today().isoformat()
    week_end = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()

    product_count = query(
        "SELECT COUNT(*) AS n FROM products WHERE status != 'hidden'",
        one=True,
        default={"n": 0},
    )["n"]

    low_stock_count = query(
        "SELECT COUNT(*) AS n FROM products WHERE stock <= ? AND status != 'hidden'",
        (get_store_settings().low_stock_limit,),
        one=True,
        default={"n": 0},
    )["n"]

    today_sales = query(
        """SELECT COUNT(*) AS n, COALESCE(SUM(total_amount), 0) AS total
             FROM orders
            WHERE DATE(order_date) = ?
              AND COALESCE(status, 'completed') != 'cancelled'""",
        (today,),
        one=True,
        default={"n": 0, "total": 0},
    )

    upcoming_appointments = query(
        """SELECT COUNT(*) AS n FROM appointments
            WHERE appt_date >= ? AND appt_date <= ? AND status = 'scheduled'""",
        (today, week_end),
        one=True,
        default={"n": 0},
    )["n"]

    return render_template(
        "admin.html",
        user=user,
        active="admin",
        title="Administration",
        staff=staff,
        active_staff_count=active_staff_count,
        activity=activity,
        product_count=product_count,
        low_stock_count=low_stock_count,
        orders_today=today_sales["n"],
        sales_today=today_sales["total"],
        upcoming_appointments=upcoming_appointments,
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
            "must_change_password": bool(row["must_change_password"]),
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
        return jsonify(ok=False, error="Username and email are required"), 400

    if role not in ROLES or role == "admin":
        return jsonify(ok=False, error="Invalid role"), 400

    if "@" not in email or "." not in email:
        return jsonify(ok=False, error="Invalid email"), 400

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
        return jsonify(ok=False, error="Username or email already exists"), 409

    record_activity(
        user_id=user["user_id"],
        action="staff_created",
        description=f"Created staff account for {username}",
        entity_type="user",
        entity_id=new_id,
    )

    return jsonify(ok=True, temp_password=temporary_password, user_id=new_id)


@app.post("/api/admin/staff/<int:user_id>/role")
@admin_required
def api_admin_set_role(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(ok=False, error="You can't change your own role"), 400

    data = request.get_json(force=True) or {}
    role = (data.get("role") or "").strip()

    if role not in ROLES or role == "admin":
        return jsonify(ok=False, error="Invalid role"), 400

    account = query("SELECT username FROM users WHERE user_id = ?", (user_id,), one=True)

    if not account:
        return jsonify(ok=False, error="User not found"), 404

    set_user_role(user_id, role)

    record_activity(
        user_id=user["user_id"],
        action="role_changed",
        description=f"Changed {account['username']}'s role to {role}",
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/toggle-active")
@admin_required
def api_admin_toggle_active(user, user_id):
    if user_id == user["user_id"]:
        return jsonify(ok=False, error="You can't deactivate yourself"), 400

    data = request.get_json(force=True) or {}
    active = bool(data.get("active", True))

    account = query("SELECT username FROM users WHERE user_id = ?", (user_id,), one=True)

    if not account:
        return jsonify(ok=False, error="User not found"), 404

    set_user_active(user_id, active)

    status_text = "Activated" if active else "Deactivated"

    record_activity(
        user_id=user["user_id"],
        action="staff_status_changed",
        description=f"{status_text} staff account {account['username']}",
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(ok=True)


@app.post("/api/admin/staff/<int:user_id>/reset-password")
@admin_required
def api_admin_reset_password(user, user_id):
    data = request.get_json(force=True) or {}
    phrase = (data.get("phrase") or "").strip()

    account = query("SELECT username FROM users WHERE user_id = ?", (user_id,), one=True)

    if not account:
        return jsonify(ok=False, error="User not found"), 404

    seed_phrase = phrase or account["username"]
    temporary_password = make_default_password(seed_phrase)

    db = connect_db()
    db.execute(
        "UPDATE users SET password = ?, must_change_password = 1 WHERE user_id = ?",
        (hash_pw(temporary_password), user_id),
    )
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM remember_tokens WHERE user_id = ?", (user_id,))
    db.commit()
    db.close()

    record_activity(
        user_id=user["user_id"],
        action="password_reset",
        description=f"Reset the password for {account['username']}",
        entity_type="user",
        entity_id=user_id,
    )

    return jsonify(ok=True, temp_password=temporary_password)
