import os
from backend.auth import forgot_password, send_email
from backend.database import connect_db

db = connect_db()
print("Accounts in database:")
for r in db.execute("SELECT username, email, deactivated_at FROM users"):
    status = "deactivated" if r["deactivated_at"] else "active"
    print(" ", r["username"], "|", r["email"], "|", status)
db.close()

email = input("\nEnter the email to test: ").strip()
print("GMAIL_USER loaded:", os.environ.get("GMAIL_USER"))

print("Direct send test:", send_email(email, "Brewskers test", "Hello from Brewskers"))

forgot_password(email)

db = connect_db()
rows = db.execute(
    "SELECT otp_id, user_id, expires_at, used_at FROM otps "
    "ORDER BY otp_id DESC LIMIT 3"
).fetchall()
print("\nLatest OTP rows:")
for r in rows:
    print(" ", dict(r))
db.close()