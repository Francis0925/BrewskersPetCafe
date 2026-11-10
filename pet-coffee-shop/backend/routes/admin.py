# Brewskers administration routes
# Admin dashboard, staff management and password resets

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

    active_staff_count = sum(1 for account in staff if not account["deactivated_at"])

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
