import sqlite3
import hashlib
import secrets
import datetime
import os
from email.message import EmailMessage

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, make_response

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

def connect_db():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path  = os.path.join(base_dir, "petcoffeeshop.db")
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    return conn

def signup(username, email, password, role="staff"):
    if len(password) < 8: return False
    db = connect_db(); cur = db.cursor()
    cur.execute("SELECT 1 FROM users WHERE email = ? OR username = ?", (email, username))
    if cur.fetchone():
        db.close(); return False
    cur.execute(
        "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
        (username, email, hashlib.sha256(password.encode()).hexdigest(), role)
    )
    db.commit(); db.close(); return True

def login(login_input, password, remember=False):
    db = connect_db(); db_cursor = db.cursor()
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    query = "SELECT * FROM users WHERE (email = ? OR username = ?) AND password = ?"
    db_cursor.execute(query, (login_input, login_input, hashed_pw))
    user = db_cursor.fetchone()
    if user:
        session = secrets.token_hex(32)
        now = datetime.datetime.now()
        if remember:
            expire = now + datetime.timedelta(days=30)
            db_cursor.execute("INSERT INTO remember_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
                              (user['user_id'], session, expire))
        else:
            expire = now + datetime.timedelta(hours=8)
            db_cursor.execute("INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
                              (user['user_id'], session, expire))
        db.commit(); db.close()
        return session, user['role']
    db.close()
    return None, None

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
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(sender, app_pw); server.send_message(msg)
        return True
    except Exception:
        return False

def forgot_password(email):
    db = connect_db(); db_cursor = db.cursor()
    db_cursor.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
    user = db_cursor.fetchone()
    if user:
        otp_code = str(secrets.randbelow(900000) + 100000)
        expire = datetime.datetime.now() + datetime.timedelta(minutes=10)
        db_cursor.execute(
            "INSERT INTO otps (user_id, otp_code, purpose, expires_at) VALUES (?, ?, 'reset', ?)",
            (user['user_id'], otp_code, expire)
        )
        db.commit()
        body = (f"Hi {user['username']},\n\n"
                f"Your password reset code is: {otp_code}\n\n"
                f"This code expires in 10 minutes. If you didn't request this, ignore this email.\n\n"
                f"- Pet Coffee Shop")
        send_email(email, "Your password reset code", body)
    db.close()

def reset_password(email, otp_code, new_pass):
    if len(new_pass) < 8: return False
    db = connect_db(); db_cursor = db.cursor()
    now = datetime.datetime.now()
    query = """
        SELECT otps.otp_id, users.user_id
        FROM otps JOIN users ON users.user_id = otps.user_id
        WHERE users.email = ? AND otps.otp_code = ? AND otps.purpose = 'reset'
        AND otps.used_at IS NULL AND otps.expires_at > ?
    """
    db_cursor.execute(query, (email, otp_code, now))
    match = db_cursor.fetchone()
    if match:
        hashed_pw = hashlib.sha256(new_pass.encode()).hexdigest()
        db_cursor.execute("UPDATE users SET password = ? WHERE user_id = ?", (hashed_pw, match['user_id']))
        db_cursor.execute("UPDATE otps SET used_at = ? WHERE otp_id = ?", (now, match['otp_id']))
        db_cursor.execute("DELETE FROM sessions WHERE user_id = ?", (match['user_id'],))
        db.commit(); db.close()
        return True
    db.close()
    return False

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("login.html")

@app.post("/api/signup")
def api_signup():
    d = request.get_json(force=True)
    username = (d.get("username") or "").strip()
    email    = (d.get("email")    or "").strip()
    password = d.get("password") or ""
    if not username or not email: return jsonify(ok=False, error="Username and email are required")
    if len(password) < 8:         return jsonify(ok=False, error="Password too short")
    if signup(username, email, password):
        return jsonify(ok=True)
    return jsonify(ok=False, error="User already exists")

@app.post("/api/login")
def api_login():
    d = request.get_json(force=True)
    remember = bool(d.get("remember"))
    session, role = login((d.get("login") or "").strip(), d.get("password") or "", remember)
    if not session: return jsonify(ok=False, error="Invalid credentials")
    resp = make_response(jsonify(ok=True, role=role))
    resp.set_cookie("session", session, httponly=True, samesite="Lax",
                    max_age=30 * 24 * 3600 if remember else 8 * 3600)
    return resp

@app.post("/api/forgot-password")
def api_forgot():
    forgot_password((request.get_json(force=True).get("email") or "").strip())
    return jsonify(ok=True)

@app.post("/api/reset-password")
def api_reset():
    d = request.get_json(force=True)
    new_pass = d.get("new_password") or ""
    if len(new_pass) < 8: return jsonify(ok=False, error="Password too short")
    if reset_password((d.get("email") or "").strip(), (d.get("otp") or "").strip(), new_pass):
        return jsonify(ok=True)
    return jsonify(ok=False, error="Invalid or expired code")

if __name__ == "__main__":
    app.run(debug=True)