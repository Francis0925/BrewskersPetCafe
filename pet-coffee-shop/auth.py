# Brewskers — authentication and password helpers.

import datetime
import hashlib
import os
import random
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

from security import (
    client_ip,
    env_flag,
    init_security,
    json_body,
    too_many,
    validate_password,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))


# --- application ---------------------------------------------------------

app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get(
        "SECRET_KEY",
        "development-only-change-before-production",
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# Security headers, CSRF checks, error pages and private logging.
init_security(app)


# --- database ------------------------------------------------------------

def connect_db():
    database_path = os.environ.get(
        "DATABASE_PATH",
        os.path.join(BASE_DIR, "petcoffeeshop.db"),
    )

    conn = sqlite3.connect(database_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --- password hashing ----------------------------------------------------

def hash_pw(password):
    """Create a secure, salted password hash."""
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    """Verify current hashes and transparently upgrade legacy SHA-256 hashes."""
    if not stored_hash or not password:
        return False

    is_legacy_hash = (
        len(stored_hash) == 64
        and all(character in "0123456789abcdefABCDEF"
                for character in stored_hash)
    )

    if is_legacy_hash:
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        is_valid = secrets.compare_digest(stored_hash, legacy_hash)
    else:
        try:
            is_valid = check_password_hash(stored_hash, password)
        except (TypeError, ValueError):
            is_valid = False

    return is_valid


def uses_legacy_hash(stored_hash):
    """Return whether a stored password still uses the old SHA-256 format."""
    return (
        isinstance(stored_hash, str)
        and len(stored_hash) == 64
        and all(character in "0123456789abcdefABCDEF"
                for character in stored_hash)
    )


# --- temporary passwords -------------------------------------------------

def make_default_password(phrase):
    """Turn a phrase such as 'maria' into 'maria4729'."""
    base = (phrase or "brewskers").strip().lower().replace(" ", "")
    base = "".join(
        character
        for character in base
        if character.isalnum() or character in "-_."
    )
    base = base[:32] or "brewskers"

    suffix = random.SystemRandom().randint(0, 9999)
    return f"{base}{suffix:04d}"


# --- staff accounts ------------------------------------------------------

def create_user(
    username,
    email,
    password,
    role="cashier",
    created_by=None,
    must_change_password=True,
):
    """Create a staff account and return its ID, or None if it already exists."""
    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO users "
            "(username, email, password, role, must_change_password, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                username,
                email,
                hash_pw(password),
                role,
                1 if must_change_password else 0,
                created_by,
            ),
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        db.rollback()
        return None
    finally:
        db.close()


def list_users():
    db = connect_db()
    rows = db.execute(
        "SELECT user_id, username, email, role, must_change_password, "
        "deactivated_at, created_at, last_login_at "
        "FROM users "
        "ORDER BY username"
    ).fetchall()
    db.close()
    return rows


def set_user_role(user_id, role):
    db = connect_db()
    db.execute(
        "UPDATE users SET role = ? WHERE user_id = ?",
        (role, user_id),
    )
    db.commit()
    db.close()


def set_user_active(user_id, active):
    db = connect_db()
    db.execute(
        "UPDATE users SET deactivated_at = ? WHERE user_id = ?",
        (None if active else datetime.datetime.now(), user_id),
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


def change_password(user_id, new_password, keep_token=None):
    """Save a new password and sign out every other device.

    keep_token is the caller's own session token, so they stay logged in.
    """
    db = connect_db()
    db.execute(
        "UPDATE users "
        "SET password = ?, must_change_password = 0 "
        "WHERE user_id = ?",
        (hash_pw(new_password), user_id),
    )
    db.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token != ?",
        (user_id, keep_token or ""),
    )
    db.execute(
        "DELETE FROM remember_tokens WHERE user_id = ? AND token != ?",
        (user_id, keep_token or ""),
    )
    db.commit()
    db.close()


# --- login attempt tracking ----------------------------------------------

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 10

# This is intentionally kept in memory. It is suitable for a small,
# single-process class project and is easy to explain during review.
failed_login_attempts = {}


def login_is_locked(username):
    """Return whether the username is temporarily locked."""
    record = failed_login_attempts.get(username)

    if not record:
        return False

    attempts, last_attempt = record
    lock_age = datetime.datetime.now() - last_attempt

    if lock_age > datetime.timedelta(minutes=LOCKOUT_MINUTES):
        failed_login_attempts.pop(username, None)
        return False

    return attempts >= MAX_FAILED_ATTEMPTS


def record_failed_login(username):
    """Record one failed password attempt for the username."""
    attempts, _ = failed_login_attempts.get(username, (0, None))
    failed_login_attempts[username] = (
        attempts + 1,
        datetime.datetime.now(),
    )


def failed_login_count(username):
    """Return how many failed attempts are currently recorded."""
    record = failed_login_attempts.get(username)
    return record[0] if record else 0


def lock_minutes_left(username):
    """Return whole minutes (at least 1) until the lock expires."""
    record = failed_login_attempts.get(username)
    if not record:
        return 0
    _, last_attempt = record
    unlock_at = last_attempt + datetime.timedelta(minutes=LOCKOUT_MINUTES)
    seconds = (unlock_at - datetime.datetime.now()).total_seconds()
    return max(1, int(-(-seconds // 60)))


def clear_failed_logins(username):
    """Clear the attempt counter after a successful login or account change."""
    failed_login_attempts.pop(username, None)


# --- login and sessions --------------------------------------------------

def login(username, password, remember=False):
    """Return (session_token, user_dict, error_code)."""
    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        )
        user = cursor.fetchone()

        if not user or not verify_password(user["password"], password):
            return None, None, "invalid"

        if user["deactivated_at"]:
            return None, None, "deactivated"

        # Upgrade old SHA-256 hashes after the user proves their password.
        if uses_legacy_hash(user["password"]):
            cursor.execute(
                "UPDATE users SET password = ? WHERE user_id = ?",
                (hash_pw(password), user["user_id"]),
            )

        now = datetime.datetime.now()
        cursor.execute(
            "UPDATE users SET last_login_at = ? WHERE user_id = ?",
            (now, user["user_id"]),
        )
        # Housekeeping: drop expired sessions so the tables don't grow forever.
        cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        cursor.execute("DELETE FROM remember_tokens WHERE expires_at < ?", (now,))
        db.commit()
    finally:
        db.close()

    token = secrets.token_urlsafe(32)

    if remember:
        expires = now + datetime.timedelta(days=30)

        db = connect_db()
        db.execute(
            "INSERT INTO remember_tokens (user_id, token, expires_at) "
            "VALUES (?, ?, ?)",
            (user["user_id"], token, expires),
        )
        db.commit()
        db.close()
    else:
        expires = now + datetime.timedelta(hours=8)

        db = connect_db()
        db.execute(
            "INSERT INTO sessions (user_id, token, expires_at) "
            "VALUES (?, ?, ?)",
            (user["user_id"], token, expires),
        )
        db.commit()
        db.close()

    return token, dict(user), None


# --- email ---------------------------------------------------------------

def send_email(to_email, subject, body):
    sender = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not sender or not app_password:
        return False

    message = EmailMessage()
    message["From"] = f"Brewskers <{sender}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, app_password)
            server.send_message(message)
        return True
    except Exception:
        app.logger.exception("Could not send password-reset email")
        return False


# --- password recovery ---------------------------------------------------

def forgot_password(email):
    """Create a reset code when the email belongs to an active account."""
    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "SELECT user_id, username FROM users "
            "WHERE email = ? AND deactivated_at IS NULL",
            (email,),
        )
        user = cursor.fetchone()

        if not user:
            return

        otp_code = str(secrets.randbelow(900000) + 100000)
        expires = datetime.datetime.now() + datetime.timedelta(minutes=10)

        cursor.execute(
            "INSERT INTO otps "
            "(user_id, otp_code, purpose, expires_at) "
            "VALUES (?, ?, 'reset', ?)",
            (user["user_id"], otp_code, expires),
        )
        db.commit()

        body = (
            f"Hi {user['username']},\n\n"
            f"Your Brewskers password reset code is: {otp_code}\n\n"
            f"This code expires in 10 minutes. "
            f"If you did not request this, ignore this email.\n\n"
            f"- Brewskers"
        )

        send_email(
            email,
            "Your Brewskers password reset code",
            body,
        )
    finally:
        db.close()


def reset_password(email, otp_code, new_password):
    """Reset a password using a valid, unused reset code."""
    if len(new_password) < 8:
        return False

    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            """SELECT otps.otp_id, users.user_id
                 FROM otps
                 JOIN users ON users.user_id = otps.user_id
                WHERE users.email = ?
                  AND users.deactivated_at IS NULL
                  AND otps.otp_code = ?
                  AND otps.purpose = 'reset'
                  AND otps.used_at IS NULL
                  AND otps.expires_at > ?""",
            (
                email,
                otp_code,
                datetime.datetime.now(),
            ),
        )
        match = cursor.fetchone()

        if not match:
            return False

        cursor.execute(
            "UPDATE users "
            "SET password = ?, must_change_password = 0 "
            "WHERE user_id = ?",
            (hash_pw(new_password), match["user_id"]),
        )
        cursor.execute(
            "UPDATE otps SET used_at = ? WHERE otp_id = ?",
            (
                datetime.datetime.now(),
                match["otp_id"],
            ),
        )
        cursor.execute(
            "DELETE FROM sessions WHERE user_id = ?",
            (match["user_id"],),
        )
        cursor.execute(
            "DELETE FROM remember_tokens WHERE user_id = ?",
            (match["user_id"],),
        )
        db.commit()
        return True
    finally:
        db.close()


# --- public routes -------------------------------------------------------

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
        return jsonify(
            ok=False,
            error="Invalid username or password",
        ), 400

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
            error=(
                "Too many failed attempts. "
                f"Try again in {lock_minutes_left(username)} minute(s)."
            ),
        ), 429

    token, user, error = login(
        username,
        password,
        remember,
    )

    if error == "deactivated":
        return jsonify(
            ok=False,
            error="This account has been deactivated",
        ), 403

    if not token:
        record_failed_login(username)
        app.logger.warning(
            "Failed login for %r from %s", username, client_ip()
        )
        attempts_left = MAX_FAILED_ATTEMPTS - failed_login_count(username)

        if attempts_left <= 0:
            return jsonify(
                ok=False,
                locked=True,
                error=(
                    "Too many failed attempts. "
                    f"Try again in {LOCKOUT_MINUTES} minutes."
                ),
            ), 429

        plural = "" if attempts_left == 1 else "s"
        return jsonify(
            ok=False,
            attempts_left=attempts_left,
            error=(
                "Wrong username or password. "
                f"{attempts_left} attempt{plural} left."
            ),
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
        return jsonify(
            ok=False,
            error="Email is required",
        ), 400

    if (
        too_many(f"forgot-ip:{client_ip()}", 5, 600)
        or too_many(f"forgot-email:{email.lower()}", 3, 600)
    ):
        return jsonify(
            ok=False,
            error="Too many requests. Please wait a few minutes.",
        ), 429

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

    return jsonify(
        ok=False,
        error="Invalid or expired code",
    ), 400


if __name__ == "__main__":
    # Never run with debug=True on a real server: it exposes a remote console.
    app.run(debug=env_flag("FLASK_DEBUG"))