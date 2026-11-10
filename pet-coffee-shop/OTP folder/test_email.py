import os, smtplib
from dotenv import load_dotenv

load_dotenv(".env")
user = os.environ.get("GMAIL_USER")
pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")

print("GMAIL_USER loaded:", user)
print("App password length (should be 16):", len(pw))

try:
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
        s.starttls()
        s.login(user, pw)
    print("SUCCESS: Gmail login worked")
except Exception as e:
    print("FAILED:", type(e).__name__, e)