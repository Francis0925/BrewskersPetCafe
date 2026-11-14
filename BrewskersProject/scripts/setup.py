# Brewskers database setup
# Run this once for a new installation.
# This script deletes the existing database before recreating it.

import os
import sqlite3

from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = PROJECT_ROOT

load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_PATH = os.environ.get(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "petcoffeeshop.db"),
)


def setup():
    if os.path.exists(DATABASE_PATH):
        os.remove(DATABASE_PATH)

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.executescript(
        """
        CREATE TABLE users (
            user_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username             TEXT NOT NULL UNIQUE,
            email                TEXT NOT NULL UNIQUE,
            password             TEXT NOT NULL,
            role                 TEXT NOT NULL DEFAULT 'viewer',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            deactivated_at       DATETIME DEFAULT NULL,
            created_by           INTEGER REFERENCES users(user_id),
            created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login_at        DATETIME DEFAULT NULL
        );

        CREATE TABLE sessions (
            session_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token       TEXT    NOT NULL UNIQUE,
            expires_at  DATETIME NOT NULL
        );

        CREATE TABLE remember_tokens (
            token_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token      TEXT    NOT NULL UNIQUE,
            expires_at DATETIME NOT NULL
        );

        CREATE TABLE otps (
            otp_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            otp_code   TEXT    NOT NULL,
            purpose    TEXT    NOT NULL,
            expires_at DATETIME NOT NULL,
            used_at    DATETIME DEFAULT NULL
        );

        CREATE TABLE store_profile (
            store_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT NOT NULL,
            address    TEXT,
            phone      TEXT,
            email      TEXT
        );

        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT NOT NULL,
            name       TEXT NOT NULL,
            price      REAL NOT NULL,
            stock      INTEGER NOT NULL DEFAULT 0,
            status     TEXT DEFAULT 'available',
            image      TEXT
        );

        CREATE TABLE orders (
            order_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no       TEXT NOT NULL UNIQUE,
            customer_name  TEXT,
            total_amount   REAL NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            amount_paid    REAL,
            change_amount  REAL,
            order_date     DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by     INTEGER REFERENCES users(user_id),
            status         TEXT NOT NULL DEFAULT 'queued'
        );

        CREATE TABLE order_items (
            item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    INTEGER NOT NULL REFERENCES orders(order_id),
            product_id  INTEGER NOT NULL REFERENCES products(product_id),
            quantity    INTEGER NOT NULL,
            price       REAL NOT NULL
        );

        CREATE TABLE services (
            service_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            price      REAL NOT NULL,
            duration   INTEGER DEFAULT 30,
            active     INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_name   TEXT NOT NULL,
            pet_type   TEXT DEFAULT 'Dog',
            breed      TEXT,
            pet_age    TEXT,
            owner_name TEXT NOT NULL,
            phone      TEXT NOT NULL,
            service_id INTEGER NOT NULL REFERENCES services(service_id),
            appt_date  DATE NOT NULL,
            appt_time  TIME NOT NULL,
            status     TEXT DEFAULT 'scheduled',
            notes      TEXT,
            photo      TEXT,
            created_by INTEGER REFERENCES users(user_id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE activity_log (
            activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(user_id),
            action      TEXT NOT NULL,
            entity_type TEXT,
            entity_id   INTEGER,
            description TEXT NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX idx_activity_log_created
        ON activity_log(created_at DESC);
        """
    )

    cursor.execute(
        "INSERT INTO store_profile "
        "(store_name, address, phone, email) "
        "VALUES (?, ?, ?, ?)",
        (
            "Brewskers",
            "123 Sample St",
            "0900-000-0000",
            "hello@brewskers.example",
        ),
    )

    cursor.execute(
        "INSERT INTO users "
        "(username, email, password, role, must_change_password) "
        "VALUES (?, ?, ?, 'admin', 0)",
        (
            "admin",
            "admin@brewskers.test",
            generate_password_hash("12345678"),
        ),
    )

    menu = [
        ("Coffee", "Cappuccino", 130),
        ("Coffee", "Caramel Macchiato", 150),
        ("Coffee", "Cold Brew", 145),
        ("Coffee", "Espresso", 90),
        ("Coffee", "Matcha Latte", 155),
        ("Pastry", "Banana Bread", 75),
        ("Pastry", "Pain au Chocolat", 95),
        ("Pastry", "Cinnamon Roll", 100),
        ("Pastry", "Tiramisu Slice", 140),
        ("Pastry", "Chocolate Cookie", 60),
        ("Pet Treats", "Bacon Bites", 75),
        ("Pet Treats", "Chicken Jerky", 90),
        ("Pet Treats", "Salmon Strips", 95),
        ("Pet Treats", "Peanut Butter Cookie", 70),
        ("Pet Treats", "Tuna Treat", 70),
    ]

    cursor.executemany(
        "INSERT INTO products "
        "(category, name, price, stock) "
        "VALUES (?, ?, ?, 25)",
        menu,
    )

    services = [
        ("Bath & Brush", 350, 45),
        ("Full Groom", 850, 90),
        ("Nail Trim", 150, 15),
        ("Teeth Brushing", 200, 20),
        ("Vet Checkup", 500, 30),
        ("Vaccination", 450, 20),
        ("Flea Treatment", 400, 30),
        ("Pet Spa Package", 1500, 120),
    ]

    cursor.executemany(
        "INSERT INTO services (name, price, duration) "
        "VALUES (?, ?, ?)",
        services,
    )

    conn.commit()
    conn.close()

    print("Brewskers database ready.")
    print("Login: admin / 12345678")


if __name__ == "__main__":
    setup()
