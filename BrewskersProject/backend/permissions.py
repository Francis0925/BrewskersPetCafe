# Brewskers permissions and access control
# Roles, permissions, current user lookup and route decorators

from functools import wraps

from flask import jsonify, redirect, request

from backend.config import PERMISSIONS
from backend.database import connect_db


def current_user():
    """Return the logged-in user when the session cookie is valid."""
    token = request.cookies.get("session")

    if not token:
        return None

    db = connect_db()
    try:
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
    except Exception:
        # Database was just restored or is still being repaired.
        return None
    finally:
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
                return jsonify(ok=False, error="Please log in"), 401
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
                    return jsonify(ok=False, error="Please log in"), 401
                return redirect("/")

            if user["must_change_password"] and not request.path.startswith(
                ("/first-login", "/api/profile/change-password", "/logout", "/static")
            ):
                return redirect("/first-login")

            if not user_has(user, permission):
                if request.path.startswith("/api/"):
                    return jsonify(ok=False, error="Not allowed"), 403
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
                return jsonify(ok=False, error="Admins only"), 403
            return redirect("/dashboard")

        return view(user, *args, **kwargs)

    return wrapper
