import mysql.connector
import hashlib
import random
import datetime
import os
import secrets
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
# Database connection
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="123456789", 
        database="petcoffeeshop_db"
    )

# User signup
def signup(username, email, password, role="staff"):
    if len(password) < 8:
        print("Error: Password too short")
        return False

    db = connect_db()
    db_cursor = db.cursor()

    hashed_pw = hashlib.sha256(password.encode()).hexdigest()

    db_cursor.execute("SELECT * FROM users WHERE email = %s OR username = %s", (email, username))
    if db_cursor.fetchone() != None:
        print("Error: User exists")
        db.close()
        return False

    db_cursor.execute(
        "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
        (username, email, hashed_pw, role)
    )
    db.commit()
    print("Success: Account created")
    db.close()
    return True

# User login
def login(login_input, password, remember=False):
    db = connect_db()
    db_cursor = db.cursor(dictionary=True)

    hashed_pw = hashlib.sha256(password.encode()).hexdigest()

    query = "SELECT * FROM users WHERE (email = %s OR username = %s) AND password = %s"
    db_cursor.execute(query, (login_input, login_input, hashed_pw))
    user = db_cursor.fetchone()

    if user:
        print(f"Success: Welcome {user['username']}")
        
        session = str(random.randint(100000, 999999)) + "session"
        now = datetime.datetime.now()
        
        if remember:
            expire = now + datetime.timedelta(days=30)
            db_cursor.execute("INSERT INTO remember_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)", (user['user_id'], session, expire))
        else:
            expire = now + datetime.timedelta(hours=8)
            db_cursor.execute("INSERT INTO sessions (user_id, token, expires_at) VALUES (%s, %s, %s)", (user['user_id'], session, expire))
        
        db.commit()
        db.close()
        return session, user['role']
    else:
        print("Error: Invalid credentials")
        db.close()
        return None, None

# Send email through Gmail
def send_email(to_email, subject, body):
    sender = os.environ.get("GMAIL_USER")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not app_pw:
        print("Error: GMAIL_USER / GMAIL_APP_PASSWORD not set")
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
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# Forgot password
def forgot_password(email):
    db = connect_db()
    db_cursor = db.cursor(dictionary=True)
    
    db_cursor.execute("SELECT user_id, username FROM users WHERE email = %s", (email,))
    user = db_cursor.fetchone()

    if user:
        otp_code = str(secrets.randbelow(900000) + 100000)
        expire = datetime.datetime.now() + datetime.timedelta(minutes=10)
        
        db_cursor.execute(
            "INSERT INTO otps (user_id, otp_code, purpose, expires_at) VALUES (%s, %s, 'reset', %s)",
            (user['user_id'], otp_code, expire)
        )
        db.commit()
        
        body = (
            f"Hi {user['username']},\n\n"
            f"Your password reset code is: {otp_code}\n\n"
            f"This code expires in 10 minutes. If you didn't request this, "
            f"you can ignore this email.\n\n- Pet Coffee Shop"
        )
        if send_email(email, "Your password reset code", body):
            print(f"Email sent: {email}")
        else:
            print("Error: Could not send email")
    else:
        print("Error: Email not found")
        
    db.close()

# Reset password
def reset_password(email, otp_code, new_pass):
    if len(new_pass) < 8:
        print("Error: Password too short")
        return False

    db = connect_db()
    db_cursor = db.cursor(dictionary=True)
    now = datetime.datetime.now()

    query = """
        SELECT otps.otp_id, users.user_id 
        FROM otps 
        JOIN users ON users.user_id = otps.user_id 
        WHERE users.email = %s AND otps.otp_code = %s AND otps.purpose = 'reset' 
        AND otps.used_at IS NULL AND otps.expires_at > %s
    """
    db_cursor.execute(query, (email, otp_code, now))
    match = db_cursor.fetchone()

    if match:
        hashed_pw = hashlib.sha256(new_pass.encode()).hexdigest()
        
        db_cursor.execute("UPDATE users SET password = %s WHERE user_id = %s", (hashed_pw, match['user_id']))
        db_cursor.execute("UPDATE otps SET used_at = %s WHERE otp_id = %s", (now, match['otp_id']))
        db_cursor.execute("DELETE FROM sessions WHERE user_id = %s", (match['user_id'],))
        
        db.commit()
        print("Success: Password changed")
        db.close()
        return True
    else:
        print("Error: Invalid OTP")
        db.close()
        return False


# ---------------------------------------------------------------
# Web layer: serves the login page and calls the functions above
# Run:  pip install flask mysql-connector-python
#       python app.py   ->  http://127.0.0.1:5000
# ---------------------------------------------------------------
from flask import Flask, render_template, request, jsonify, make_response

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("login.html")


@app.post("/api/signup")
def api_signup():
    d = request.get_json(force=True)
    username = (d.get("username") or "").strip()
    email = (d.get("email") or "").strip()
    password = d.get("password") or ""
    if not username or not email:
        return jsonify(ok=False, error="Username and email are required")
    if len(password) < 8:
        return jsonify(ok=False, error="Password too short")
    # role is never taken from the browser; new accounts are always "staff"
    if signup(username, email, password):
        return jsonify(ok=True)
    return jsonify(ok=False, error="User already exists")


@app.post("/api/login")
def api_login():
    d = request.get_json(force=True)
    remember = bool(d.get("remember"))
    session, role = login((d.get("login") or "").strip(), d.get("password") or "", remember)
    if not session:
        return jsonify(ok=False, error="Invalid credentials")
    resp = make_response(jsonify(ok=True, role=role))
    resp.set_cookie("session", session, httponly=True, samesite="Lax",
                    max_age=30 * 24 * 3600 if remember else 8 * 3600)
    return resp


@app.post("/api/forgot-password")
def api_forgot():
    d = request.get_json(force=True)
    forgot_password((d.get("email") or "").strip())  # OTP is printed in this terminal
    return jsonify(ok=True)


@app.post("/api/reset-password")
def api_reset():
    d = request.get_json(force=True)
    new_pass = d.get("new_password") or ""
    if len(new_pass) < 8:
        return jsonify(ok=False, error="Password too short")
    if reset_password((d.get("email") or "").strip(), (d.get("otp") or "").strip(), new_pass):
        return jsonify(ok=True)
    return jsonify(ok=False, error="Invalid or expired code")


if __name__ == "__main__":
    app.run(debug=True)