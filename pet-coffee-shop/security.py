# Brewskers — security helpers.
#
# Pure helpers plus init_security(app). This module must NOT import auth.py
# (auth.py imports it), so everything here works on the Flask app it is given.

import hashlib
import hmac
import datetime
import logging
import os
import re
import threading
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from flask import jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --- small utilities -----------------------------------------------------

def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def json_body():
    """Return the JSON body as a dict. Bad or missing JSON becomes {}."""
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def client_ip():
    return request.remote_addr or "unknown"


# --- rate limiting (in memory, fine for a single-process app) ------------

_hits = {}
_hits_lock = threading.Lock()


def too_many(key, limit, window_seconds):
    """Record one hit for `key`; return True if it went over the limit."""
    now = time.time()
    with _hits_lock:
        recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
        if len(recent) >= limit:
            _hits[key] = recent
            return True
        recent.append(now)
        _hits[key] = recent
        return False


# --- input validation ----------------------------------------------------

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PHONE_RE = re.compile(r"^(\+63|0)9\d{9}$")
PHOTO_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")
MAX_PHOTO_CHARS = 1_500_000

COMMON_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "iloveyou", "admin123", "welcome1", "letmein1", "brewskers",
}


def validate_password(password, username=""):
    """Return an error message, or None when the password is acceptable."""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > 128:
        return "Password must be 128 characters or fewer"
    if username and password.lower() == username.lower():
        return "Password can't be the same as the username"
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common. Choose another one"
    return None


def validate_email(email):
    return len(email) <= 120 and bool(EMAIL_RE.match(email))


def _bad_text(value):
    return bool(re.search(r'[<>"\x00-\x1f]', value))


def validate_appointment(data):
    """Return (clean_dict, error). Everything is checked on the server."""
    def text(key, label, max_len, required=False, digits_ok=True):
        value = str(data.get(key) or "").strip()
        if required and not value:
            return None, f"{label} is required"
        if len(value) > max_len:
            return None, f"{label} must be {max_len} characters or fewer"
        if _bad_text(value):
            return None, f"{label} contains characters that aren't allowed"
        if not digits_ok and re.search(r"\d", value):
            return None, f"{label} can't contain numbers"
        return value, None

    clean = {}
    for key, label, size, required, digits_ok in (
        ("pet_name", "Pet name", 30, True, False),
        ("breed", "Breed", 30, False, False),
        ("pet_age", "Age", 20, False, True),
        ("owner_name", "Owner name", 40, True, False),
        ("notes", "Guest notes", 500, False, True),
    ):
        value, error = text(key, label, size, required, digits_ok)
        if error:
            return None, error
        clean[key] = value

    pet_type = str(data.get("pet_type") or "Dog")
    if pet_type not in ("Dog", "Cat"):
        return None, "Pet type must be Dog or Cat"
    clean["pet_type"] = pet_type

    phone = re.sub(r"[\s-]", "", str(data.get("phone") or ""))
    if not PHONE_RE.match(phone):
        return None, "Enter a valid Philippine mobile number"
    clean["phone"] = phone

    try:
        clean["service_id"] = int(data.get("service_id"))
    except (TypeError, ValueError):
        return None, "Choose a service"

    try:
        day = datetime.date.fromisoformat(str(data.get("appt_date") or ""))
    except ValueError:
        return None, "Choose a valid date"
    if day < datetime.date.today():
        return None, "The appointment date can't be in the past"
    clean["appt_date"] = day.isoformat()

    try:
        moment = datetime.datetime.strptime(
            str(data.get("appt_time") or ""), "%H:%M"
        )
    except ValueError:
        return None, "Choose a valid time"
    clean["appt_time"] = moment.strftime("%H:%M")

    photo = data.get("photo") or None
    if photo is not None:
        if (
            not isinstance(photo, str)
            or len(photo) > MAX_PHOTO_CHARS
            or not PHOTO_RE.match(photo)
        ):
            return None, "The photo must be a JPEG, PNG or WebP image under 1 MB"
    clean["photo"] = photo
    return clean, None


# --- CSRF ----------------------------------------------------------------
#
# The token is an HMAC of the login session cookie, so it needs no extra
# storage. Pages put it in <meta name="csrf-token"> and app.js sends it in
# the X-CSRF-Token header on every API call.

CSRF_EXEMPT = {"/api/login", "/api/forgot-password", "/api/reset-password"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def make_csrf_token(secret_key):
    session = request.cookies.get("session", "")
    if not session:
        return ""
    return hmac.new(
        str(secret_key).encode(), session.encode(), hashlib.sha256
    ).hexdigest()


# --- error pages ---------------------------------------------------------

_MESSAGES = {
    400: ("Bad request", "That request wasn't valid. Please try again."),
    403: ("Not allowed", "You don't have access to that."),
    404: ("Page not found", "We couldn't find that page."),
    405: ("Not allowed", "That action isn't allowed here."),
    413: ("Too large", "That upload is too large."),
    429: ("Slow down", "Too many requests. Please wait a moment."),
    500: ("Something went wrong", "Please try again. If it keeps happening, tell the admin."),
}


def _error_response(code):
    title, message = _MESSAGES.get(code, _MESSAGES[500])
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error=message), code
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Brewskers – {title}</title>"
        '<link rel="stylesheet" href="/static/style.css"></head>'
        '<body class="auth"><div class="auth-card">'
        f"<h1>{title}</h1><p>{message}</p>"
        '<a class="btn wide" href="/">Back to Brewskers</a>'
        "</div></body></html>"
    )
    return html, code


# --- wiring --------------------------------------------------------------

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def init_security(app):
    environment = os.environ.get("APP_ENV", "development").lower()
    production = environment == "production"

    secret = app.config.get("SECRET_KEY") or ""
    if production and (not secret or secret.startswith("development-only")):
        raise RuntimeError(
            "Set a real SECRET_KEY in your .env file before running in production."
        )

    app.config["SESSION_COOKIE_SECURE"] = production or env_flag("COOKIE_SECURE")
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request cap
    app.config["PROPAGATE_EXCEPTIONS"] = False

    # Private log file: technical details go here, never to the browser.
    log_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=1_000_000, backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    app.jinja_env.globals["csrf_token"] = lambda: make_csrf_token(
        app.config["SECRET_KEY"]
    )

    @app.before_request
    def protect_state_changes():
        if request.method not in UNSAFE_METHODS:
            return None

        # Reject cross-site form posts: the Origin host must be ours.
        origin = request.headers.get("Origin")
        if origin and origin != "null":
            if urlparse(origin).netloc != request.host:
                app.logger.warning("Blocked cross-origin request from %s", origin)
                return jsonify(ok=False, error="Request blocked."), 403

        if not request.path.startswith("/api/") or request.path in CSRF_EXEMPT:
            return None
        if not request.cookies.get("session"):
            return None  # login_required answers with 401

        sent = request.headers.get("X-CSRF-Token", "")
        expected = make_csrf_token(app.config["SECRET_KEY"])
        if not expected or not hmac.compare_digest(sent, expected):
            app.logger.warning("CSRF check failed for %s", request.path)
            return jsonify(
                ok=False,
                error="Security check failed. Refresh the page and try again.",
            ), 403
        return None

    @app.after_request
    def add_security_headers(response):
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.is_secure or app.config["SESSION_COOKIE_SECURE"]:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if not request.path.startswith("/static/"):
            headers["Cache-Control"] = "no-store"
        return response

    for code in (400, 403, 404, 405, 413, 429):
        app.register_error_handler(code, lambda error, c=code: _error_response(c))

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return _error_response(error.code or 500)
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return _error_response(500)
