# Brewskers database connection
# Single place for the database path and connection settings

import glob
import os
import sqlite3

from dotenv import load_dotenv


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = PROJECT_ROOT

load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_database_path():
    return os.environ.get(
        "DATABASE_PATH",
        os.path.join(BASE_DIR, "petcoffeeshop.db"),
    )


def get_backup_dir():
    return os.environ.get(
        "BACKUP_DIR",
        os.path.join(BASE_DIR, "backups"),
    )


_restoring = False


def connect_db():
    # If the database was deleted while the server is running, restore it
    # instead of creating a blank file that crashes every page.
    global _restoring
    if not _restoring and not _is_valid_database(get_database_path()):
        _restoring = True
        try:
            migrate_db()
        finally:
            _restoring = False

    conn = sqlite3.connect(get_database_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_count(conn):
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    except sqlite3.Error:
        return 0


def _is_valid_database(path):
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        conn.close()
        return tables > 0
    except sqlite3.Error:
        return False


def _list_backups():
    pattern = os.path.join(get_backup_dir(), "brewskers-*.db")
    return sorted(glob.glob(pattern))


def _find_latest_valid_backup():
    # Newest first, skip any blank backups created before the auto-restore fix.
    for candidate in reversed(_list_backups()):
        if _is_valid_database(candidate):
            return candidate
    return None


def _restore_from_backup(backup_path):
    target_path = get_database_path()
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    # Remove a blank live file first so the backup does not append to it.
    if os.path.exists(target_path) and not _is_valid_database(target_path):
        os.remove(target_path)
    source = sqlite3.connect(backup_path)
    target = sqlite3.connect(target_path)
    with target:
        source.backup(target)
    target.close()
    source.close()
    print(f"Database restored from backup: {os.path.basename(backup_path)}")


def _create_fresh_database():
    """Create tables and seed data when no backup exists.
    Keep this schema in sync with scripts/setup.py."""
    from werkzeug.security import generate_password_hash

    path = get_database_path()
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.executescript(
        """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            deactivated_at DATETIME DEFAULT NULL,
            created_by INTEGER REFERENCES users(user_id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login_at DATETIME DEFAULT NULL
        );
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token TEXT NOT NULL UNIQUE,
            expires_at DATETIME NOT NULL
        );
        CREATE TABLE remember_tokens (
            token_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token TEXT NOT NULL UNIQUE,
            expires_at DATETIME NOT NULL
        );
        CREATE TABLE otps (
            otp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            otp_code TEXT NOT NULL,
            purpose TEXT NOT NULL,
            expires_at DATETIME NOT NULL,
            used_at DATETIME DEFAULT NULL
        );
        CREATE TABLE store_profile (
            store_id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            email TEXT,
            tax_rate REAL NOT NULL DEFAULT 12.0,
            low_stock_limit INTEGER NOT NULL DEFAULT 5
        );
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            status TEXT DEFAULT 'available',
            image TEXT
        );
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT NOT NULL UNIQUE,
            customer_name TEXT,
            total_amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            amount_paid REAL,
            change_amount REAL,
            order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER REFERENCES users(user_id),
            status TEXT NOT NULL DEFAULT 'queued',
            tax_rate REAL NOT NULL DEFAULT 8.0
        );
        CREATE TABLE order_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(order_id),
            product_id INTEGER NOT NULL REFERENCES products(product_id),
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        );
        CREATE TABLE services (
            service_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            duration INTEGER DEFAULT 30,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_name TEXT NOT NULL,
            pet_type TEXT DEFAULT 'Dog',
            breed TEXT,
            pet_age TEXT,
            owner_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service_id INTEGER NOT NULL REFERENCES services(service_id),
            appt_date DATE NOT NULL,
            appt_time TIME NOT NULL,
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            photo TEXT,
            created_by INTEGER REFERENCES users(user_id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE activity_log (
            activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(user_id),
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            description TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_activity_log_created ON activity_log(created_at DESC);
        """
    )
    cursor.execute(
        "INSERT INTO store_profile (store_name, address, phone, email, tax_rate, low_stock_limit) VALUES (?, ?, ?, ?, 12.0, 5)",
        ("Brewskers", "123 Sample St", "0900-000-0000", "hello@brewskers.example"),
    )
    cursor.execute(
        "INSERT INTO users (username, email, password, role, must_change_password) VALUES (?, ?, ?, 'admin', 0)",
        ("admin", "admin@brewskers.test", generate_password_hash("12345678")),
    )
    conn.commit()
    conn.close()
    print("No backup found. Created a fresh database. Login: admin / 12345678")


def migrate_db():
    """Restore a deleted or blank database, then add new columns and indexes.
    Safe to run on every startup."""
    path = get_database_path()

    # If the live file is missing or blank, restore the latest valid backup.
    if not _is_valid_database(path):
        backup = _find_latest_valid_backup()
        if backup:
            _restore_from_backup(backup)
        else:
            _create_fresh_database()

    conn = sqlite3.connect(path, timeout=10)
    try:
        # Only alter tables that exist, so a weird file never crashes startup.
        if _table_count(conn) == 0:
            conn.close()
            backup = _find_latest_valid_backup()
            if backup:
                _restore_from_backup(backup)
                conn = sqlite3.connect(path, timeout=10)
            else:
                conn.close()
                _create_fresh_database()
                conn = sqlite3.connect(path, timeout=10)

        # Orders status for Queued / Completed / Cancelled workflow
        if "orders" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            if "status" not in _columns(conn, "orders"):
                conn.execute(
                    "ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'"
                )
            conn.execute("UPDATE orders SET status = 'queued' WHERE status IS NULL OR status = ''")

        # Product picture path, for example product_images/espresso.jpg
        if "products" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            if "image" not in _columns(conn, "products"):
                conn.execute("ALTER TABLE products ADD COLUMN image TEXT")

        # Store settings: tax rate and low stock threshold used to be
        # hardcoded constants. Older databases need the columns added.
        if "tax_rate" not in _columns(conn, "store_profile"):
            conn.execute("ALTER TABLE store_profile ADD COLUMN tax_rate REAL NOT NULL DEFAULT 12.0")
        if "low_stock_limit" not in _columns(conn, "store_profile"):
            conn.execute("ALTER TABLE store_profile ADD COLUMN low_stock_limit INTEGER NOT NULL DEFAULT 5")

        # Every order remembers the tax rate that was applied to it, so old
        # receipts stay accurate after the store changes its rate. The 8.0
        # default matches the rate charged before this column existed.
        if "tax_rate" not in _columns(conn, "orders"):
            conn.execute("ALTER TABLE orders ADD COLUMN tax_rate REAL NOT NULL DEFAULT 8.0")

        # Indexes for faster filtering in data management screens
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appt_date, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_status ON products(status, category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at DESC)")

        conn.commit()
    finally:
        conn.close()
