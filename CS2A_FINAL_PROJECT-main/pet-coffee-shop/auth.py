# Brewskers — auth helpers + flask app factory
# Handles login, sessions, forgot/reset password, and admin staff helpers.

import sqlite3
import hashlib
import secrets
import smtplib
import datetime
import os
import random
from email.message import EmailMessage

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, make_response

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


# --- db helper ------------------------------------------------------------

def connect_db():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "petcoffeeshop.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# --- password hashing -----------------------------------------------------

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


# --- default password generator ------------------------------------------

def make_default_password(phrase):
    """Turn a typed phrase (e.g. 'maria') into 'maria4729'."""
    base = (phrase or "brewskers").strip().lower().replace(" ", "")
    return f"{base}{random.randint(0, 9999):04d}"


# --- user helpers (admin calls these via app.py) --------------------------

def create_user(username, email, password, role="staff",
                created_by=None, must_change_password=True):
    db = connect_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password, role, "
            "must_change_password, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, email, hash_pw(password), role,
             1 if must_change_password else 0, created_by)
        )
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        db.close()


def list_users():
    db = connect_db()
    rows = db.execute(
        "SELECT user_id, username, email, role, must_change_password, "
        "deactivated_at, created_at, last_login_at "
        "FROM users ORDER BY username"
    ).fetchall()
    db.close()
    return rows


def set_user_role(user_id, role):
    db = connect_db()
    db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    db.commit()
    db.close()


def set_user_active(user_id, active):
    db = connect_db()
    db.execute(
        "UPDATE users SET deactivated_at = ? WHERE user_id = ?",
        (None if active else datetime.datetime.now(), user_id)
    )
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM remember_tokens WHERE user_id = ?", (user_id,))
    db.commit()
    db.close()


def change_password(user_id, new_password):
    db = connect_db()
    db.execute(
        "UPDATE users SET password = ?, must_change_password = 0 "
        "WHERE user_id = ?",
        (hash_pw(new_password), user_id)
    )
    db.commit()
    db.close()


# --- login / sessions -----------------------------------------------------

def login(username, password, remember=False):
    """Returns (session_token, user_dict, error_code)."""
    db = connect_db()
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, hash_pw(password))
    )
    user = cur.fetchone()
    if not user:
        db.close()
        return None, None, "invalid"
    if user["deactivated_at"]:
        db.close()
        return None, None, "deactivated"

    token = secrets.token_hex(32)
    now = datetime.datetime.now()
    if remember:
        expires = now + datetime.timedelta(days=30)
        cur.execute(
            "INSERT INTO remember_tokens (user_id, token, expires_at) "
            "VALUES (?, ?, ?)",
            (user["user_id"], token, expires)
        )
    else:
        expires = now + datetime.timedelta(hours=8)
        cur.execute(
            "INSERT INTO sessions (user_id, token, expires_at) "
            "VALUES (?, ?, ?)",
            (user["user_id"], token, expires)
        )
    cur.execute(
        "UPDATE users SET last_login_at = ? WHERE user_id = ?",
        (now, user["user_id"])
    )
    db.commit()
    db.close()
    return token, dict(user), None


# --- email (used for forgot-password OTP) ---------------------------------

def send_email(to_email, subject, body):
    sender = os.environ.get("GMAIL_USER")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not app_pw:
        return False
    msg = EmailMessage()
    msg["From"] = f"Pet Coffee Shop <{sender}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, app_pw)
            server.send_message(msg)
        return True
    except Exception:
        return False


# --- forgot / reset password ---------------------------------------------

def forgot_password(email):
    db = connect_db()
    cur = db.cursor()
    cur.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
    user = cur.fetchone()
    if user:
        otp_code = str(secrets.randbelow(900000) + 100000)
        expires = datetime.datetime.now() + datetime.timedelta(minutes=10)
        cur.execute(
            "INSERT INTO otps (user_id, otp_code, purpose, expires_at) "
            "VALUES (?, ?, 'reset', ?)",
            (user["user_id"], otp_code, expires)
        )
        db.commit()
        body = (
            f"Hi {user['username']},\n\n"
            f"Your password reset code is: {otp_code}\n\n"
            f"This code expires in 10 minutes. If you didn't request this, "
            f"ignore this email.\n\n- Pet Coffee Shop"
        )
        send_email(email, "Your password reset code", body)
    db.close()


def reset_password(email, otp_code, new_password):
    if len(new_password) < 8:
        return False
    db = connect_db()
    cur = db.cursor()
    cur.execute(
        """SELECT otps.otp_id, users.user_id
             FROM otps JOIN users ON users.user_id = otps.user_id
            WHERE users.email = ? AND otps.otp_code = ? AND otps.purpose = 'reset'
              AND otps.used_at IS NULL AND otps.expires_at > ?""",
        (email, otp_code, datetime.datetime.now())
    )
    match = cur.fetchone()
    if not match:
        db.close()
        return False
    cur.execute(
        "UPDATE users SET password = ?, must_change_password = 0 "
        "WHERE user_id = ?",
        (hash_pw(new_password), match["user_id"])
    )
    cur.execute(
        "UPDATE otps SET used_at = ? WHERE otp_id = ?",
        (datetime.datetime.now(), match["otp_id"])
    )
    cur.execute("DELETE FROM sessions WHERE user_id = ?", (match["user_id"],))
    db.commit()
    db.close()
    return True


# --- flask app ------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("login.html")


@app.post("/api/login")
def api_login():
    d = request.get_json(force=True)
    remember = bool(d.get("remember"))
    token, user, err = login(
        (d.get("username") or "").strip(),
        d.get("password") or "",
        remember
    )
    if err == "deactivated":
        return jsonify(ok=False, error="This account has been deactivated")
    if not token:
        return jsonify(ok=False, error="Invalid username or password")
    resp = make_response(jsonify(
        ok=True,
        role=user["role"],
        must_change_password=bool(user["must_change_password"])
    ))
    resp.set_cookie(
        "session", token, httponly=True, samesite="Lax",
        max_age=30 * 24 * 3600 if remember else 8 * 3600
    )
    return resp


@app.post("/api/forgot-password")
def api_forgot():
    forgot_password((request.get_json(force=True).get("email") or "").strip())
    return jsonify(ok=True)


@app.post("/api/reset-password")
def api_reset():
    d = request.get_json(force=True)
    new_password = d.get("new_password") or ""
    if len(new_password) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters")
    if reset_password(
        (d.get("email") or "").strip(),
        (d.get("otp") or "").strip(),
        new_password
    ):
        return jsonify(ok=True)
    return jsonify(ok=False, error="Invalid or expired code")


if __name__ == "__main__":
    app.run(debug=True)