import sqlite3, os, hashlib

# ------------------------------------------------------------------ helpers
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def setup():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "petcoffeeshop.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ---------- schema (idempotent) ----------
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        expires_at DATETIME NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS remember_tokens (
        token_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        expires_at DATETIME NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS otps (
        otp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        otp_code TEXT NOT NULL,
        purpose TEXT NOT NULL,
        expires_at DATETIME NOT NULL,
        used_at DATETIME DEFAULT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS store_profile (
        store_id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_name TEXT NOT NULL,
        address TEXT,
        phone TEXT,
        email TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        emoji TEXT DEFAULT '☕',
        status TEXT DEFAULT 'available'
    );
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT NOT NULL UNIQUE,
        customer_name TEXT,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        amount_paid REAL,
        change_amount REAL,
        order_date DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS order_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    );
    CREATE TABLE IF NOT EXISTS services (
        service_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        duration INTEGER DEFAULT 30
    );
    CREATE TABLE IF NOT EXISTS appointments (
        appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_name TEXT NOT NULL,
        pet_type TEXT DEFAULT 'Dog',
        breed TEXT,
        pet_age TEXT,
        owner_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        service_id INTEGER NOT NULL,
        appt_date DATE NOT NULL,
        appt_time TIME NOT NULL,
        status TEXT DEFAULT 'scheduled',
        notes TEXT,
        photo TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (service_id) REFERENCES services(service_id)
    );
    """)

    # ---------- store profile (idempotent) ----------
    if not cursor.execute("SELECT 1 FROM store_profile").fetchone():
        cursor.execute(
            "INSERT INTO store_profile (store_name, address, phone, email) VALUES (?, ?, ?, ?)",
            ("Brewskers", "123 Sample St", "0900-000-0000", "hello@brewskers.example"))

    # ---------- admin account (so you can log in) ----------
    if not cursor.execute(
        "SELECT 1 FROM users WHERE email = ? OR username = ?",
        ("admin@brewskers.test", "admin")).fetchone():
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin@brewskers.test", hash_pw("BrewskersAdmin!"), "admin"))

    conn.commit()
    conn.close()

    print("Brewskers DB ready")
    print("Login: admin@brewskers.test / BrewskersAdmin!")

if __name__ == "__main__":
    setup()