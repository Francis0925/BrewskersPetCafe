# Brewskers profile and session routes
# Sidebar summary, logout, first login password change, landing and profile page

import datetime

from flask import jsonify, redirect, render_template, request

from backend.auth import app, change_password, connect_db, verify_password
from backend.config import LANDING_PAGE, LOW_STOCK_LIMIT
from backend.helpers import query
from backend.permissions import current_user, login_required


@app.context_processor
def sidebar_summary():
    """Provide compact daily information for the sidebar footer."""
    if request.path.startswith("/api/"):
        return {"sidebar_summary": None}

    try:
        user = current_user()
    except Exception:
        return {"sidebar_summary": None}

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
        default={"order_count": 0, "total_sales": 0},
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


@app.get("/logout")
def logout():
    token = request.cookies.get("session")

    if token:
        db = connect_db()
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.execute("DELETE FROM remember_tokens WHERE token = ?", (token,))
        db.commit()
        db.close()

    response = redirect("/")
    response.delete_cookie("session")
    return response


@app.get("/first-login")
def first_login_page():
    user = current_user()

    if not user:
        return redirect("/")

    if not user["must_change_password"]:
        return redirect("/dashboard")

    return render_template("first_login.html", user=user, title="Set your password")


@app.post("/api/profile/change-password")
@login_required
def api_change_password(user):
    # current_user is already resolved by login_required and passed as user
    data = request.get_json(force=True) or {}

    new_password = data.get("new_password") or ""
    confirm = data.get("confirm") or ""

    if len(new_password) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters"), 400

    if new_password != confirm:
        return jsonify(ok=False, error="Passwords do not match"), 400

    db = connect_db()
    account = db.execute(
        "SELECT password FROM users WHERE user_id = ?", (user["user_id"],)
    ).fetchone()
    db.close()

    if not account:
        return jsonify(ok=False, error="User not found"), 404

    if user["must_change_password"]:
        temporary_password = data.get("temporary_password") or ""

        if not temporary_password:
            return jsonify(ok=False, error="Temporary password is required"), 400

        if not verify_password(account["password"], temporary_password):
            return jsonify(ok=False, error="Temporary password is incorrect"), 403
    else:
        current_password = data.get("current_password") or ""

        if not current_password:
            return jsonify(ok=False, error="Current password is required"), 400

        if not verify_password(account["password"], current_password):
            return jsonify(ok=False, error="Current password is incorrect"), 403

    change_password(user["user_id"], new_password)
    return jsonify(ok=True)


@app.get("/landing")
def landing():
    user = current_user()

    if not user:
        return redirect("/")

    if user["must_change_password"]:
        return redirect("/first-login")

    return redirect(LANDING_PAGE.get(user["role"], "/dashboard"))


@app.get("/profile")
@login_required
def profile_page(user):
    full_account = query(
        """
        SELECT user_id, username, email, role, created_at, last_login_at
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

