# Brewskers public authentication routes
# Login page, login, forgot password and reset password endpoints

from flask import jsonify, make_response, render_template

from backend.auth import (
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    app,
    clear_failed_logins,
    failed_login_count,
    forgot_password,
    lock_minutes_left,
    login,
    login_is_locked,
    record_activity,
    record_failed_login,
    reset_password,
)
from backend.security import client_ip, json_body, too_many, validate_password


@app.get("/")
def index():
    return render_template("login.html")


@app.post("/api/login")
def api_login():
    data = json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember"))

    if not username or not password:
        return jsonify(ok=False, error="Invalid username or password"), 400

    if too_many(f"login-ip:{client_ip()}", 30, 600):
        app.logger.warning("Login rate limit hit from %s", client_ip())
        return jsonify(
            ok=False,
            error="Too many attempts from this device. Try again later.",
        ), 429

    if login_is_locked(username):
        return jsonify(
            ok=False,
            locked=True,
            error=f"Too many failed attempts. Try again in {lock_minutes_left(username)} minute(s).",
        ), 429

    token, user, error = login(username, password, remember)

    if error == "deactivated":
        return jsonify(ok=False, error="This account has been deactivated"), 403

    if not token:
        record_failed_login(username)
        record_activity(
            user_id=None,
            action="login_failed",
            description=f"Failed login for {username}",
            entity_type="user",
        )
        app.logger.warning("Failed login for %r from %s", username, client_ip())
        attempts_left = MAX_FAILED_ATTEMPTS - failed_login_count(username)

        if attempts_left <= 0:
            return jsonify(
                ok=False,
                locked=True,
                error=f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.",
            ), 429

        plural = "" if attempts_left == 1 else "s"
        return jsonify(
            ok=False,
            attempts_left=attempts_left,
            error=f"Wrong username or password. {attempts_left} attempt{plural} left.",
        ), 401

    clear_failed_logins(username)

    response = make_response(
        jsonify(
            ok=True,
            role=user["role"],
            must_change_password=bool(user["must_change_password"]),
        )
    )

    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="Lax",
        secure=app.config["SESSION_COOKIE_SECURE"],
        max_age=30 * 24 * 3600 if remember else 8 * 3600,
    )

    return response


@app.post("/api/forgot-password")
def api_forgot():
    data = json_body()
    email = (data.get("email") or "").strip()

    if not email:
        return jsonify(ok=False, error="Email is required"), 400

    if too_many(f"forgot-ip:{client_ip()}", 5, 600) or too_many(
        f"forgot-email:{email.lower()}", 3, 600
    ):
        return jsonify(ok=False, error="Too many requests. Please wait a few minutes."), 429

    forgot_password(email)

    # The generic response avoids revealing whether the email is registered.
    return jsonify(ok=True)


@app.post("/api/reset-password")
def api_reset():
    data = json_body()
    email = (data.get("email") or "").strip()
    otp_code = (data.get("otp") or "").strip()
    new_password = data.get("new_password") or ""

    password_error = validate_password(new_password)
    if password_error:
        return jsonify(ok=False, error=password_error), 400

    # A 6-digit code can be guessed, so limit the tries per email address.
    if too_many(f"reset-email:{email.lower()}", 5, 600):
        app.logger.warning("Reset-code guessing blocked for %r", email)
        return jsonify(
            ok=False,
            error="Too many attempts. Request a new code in a few minutes.",
        ), 429

    if reset_password(email, otp_code, new_password):
        return jsonify(ok=True)

    return jsonify(ok=False, error="Invalid or expired code"), 400
