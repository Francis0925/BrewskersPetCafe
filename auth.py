import mysql.connector
import hashlib
import random
import datetime

# Database connection
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="", 
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

# Forgot password
def forgot_password(email):
    db = connect_db()
    db_cursor = db.cursor(dictionary=True)
    
    db_cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
    user = db_cursor.fetchone()

    if user:
        otp_code = str(random.randint(100000, 999999))
        expire = datetime.datetime.now() + datetime.timedelta(minutes=10)
        
        db_cursor.execute(
            "INSERT INTO otps (user_id, otp_code, purpose, expires_at) VALUES (%s, %s, 'reset', %s)",
            (user['user_id'], otp_code, expire)
        )
        db.commit()
        
        print(f"Email sent: {email}")
        print(f"OTP: {otp_code}")
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