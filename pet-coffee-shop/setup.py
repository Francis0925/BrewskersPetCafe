import sqlite3, os, datetime, random, hashlib

DEMO_PREFIX = "[DEMO] "   # every seeded row starts with this so it can be wiped safely

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

    # =====================================================================
    # DEMO DATA
    # All demo rows are prefixed with [DEMO] so they're visually distinct
    # from any real data you create later, and so they can be wiped cleanly.
    # =====================================================================

    # ---------- users ----------
    demo_users = [
        ("admin",   "admin@brewskers.test",   "BrewskersAdmin!", "admin"),
        ("francis", "francis@brewskers.test", "DemoStaff#1",     "staff"),
        ("kyla",    "kyla@brewskers.test",    "DemoStaff#2",     "staff"),
        ("miguel",  "miguel@brewskers.test",  "DemoStaff#3",     "staff"),
    ]
    for username, email, password, role in demo_users:
        if not cursor.execute(
            "SELECT 1 FROM users WHERE email = ? OR username = ?",
            (email, DEMO_PREFIX + username)).fetchone():
            cursor.execute(
                "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
                (DEMO_PREFIX + username, email, hash_pw(password), role))

    # ---------- services ----------
    demo_services = [
        ("Bath & Brush",      350,  30),
        ("Full Grooming",     750,  75),
        ("Nail Trim",         150,  15),
        ("Teeth Brushing",    200,  20),
        ("Flea Treatment",    300,  25),
        ("Pawdicure",         450,  40),
        ("De-shedding",       500,  45),
        ("Spa Day (Small)",  1200, 120),
    ]
    service_ids = []
    for name, price, duration in demo_services:
        existing = cursor.execute(
            "SELECT service_id FROM services WHERE name = ?", (DEMO_PREFIX + name,)).fetchone()
        if existing:
            service_ids.append(existing["service_id"])
        else:
            cursor.execute(
                "INSERT INTO services (name, price, duration) VALUES (?, ?, ?)",
                (DEMO_PREFIX + name, price, duration))
            service_ids.append(cursor.lastrowid)

    # ---------- products ----------
    demo_products = [
        # Coffee
        ("Espresso",          "Coffee",  90,  "☕"),
        ("Americano",         "Coffee", 110,  "☕"),
        ("Cappuccino",        "Coffee", 140,  "🥛"),
        ("Café Latte",        "Coffee", 140,  "🥛"),
        ("Caramel Macchiato", "Coffee", 165,  "🍮"),
        ("Mocha",             "Coffee", 155,  "🍫"),
        ("Flat White",        "Coffee", 150,  "☕"),
        ("Spanish Latte",     "Coffee", 160,  "🥛"),
        ("Vanilla Latte",     "Coffee", 155,  "🌼"),
        ("Hazelnut Latte",    "Coffee", 155,  "🌰"),
        ("Matcha Latte",      "Coffee", 170,  "🍵"),
        ("Cold Brew",         "Coffee", 130,  "🧊"),
        # Pastry
        ("Almond Croissant",    "Pastry",  95, "🥐"),
        ("Pain au Chocolat",    "Pastry",  85, "🥐"),
        ("Blueberry Muffin",    "Pastry",  75, "🧁"),
        ("Chocolate Muffin",    "Pastry",  75, "🧁"),
        ("Cinnamon Roll",       "Pastry", 110, "🍥"),
        ("Banana Bread Slice",  "Pastry",  80, "🍌"),
        ("Cheese Danish",       "Pastry",  95, "🥐"),
        ("Apple Turnover",      "Pastry",  85, "🥧"),
        ("Chocolate Donut",     "Pastry",  70, "🍩"),
        ("Glazed Donut",        "Pastry",  65, "🍩"),
        ("Tiramisu Cup",        "Pastry", 145, "🍰"),
        ("Cheesecake Slice",    "Pastry", 160, "🍰"),
        # Pet treats
        ("Chicken Jerky",         "Treat",  60, "🍗"),
        ("Beef Strips",           "Treat",  70, "🥩"),
        ("Fish Skins",            "Treat",  85, "🐟"),
        ("Sweet Potato Chews",    "Treat",  55, "🍠"),
        ("Peanut Butter Cookies", "Treat",  75, "🥜"),
        ("Pumpkin Biscuits",      "Treat",  65, "🎃"),
        ("Yogurt Drops",          "Treat",  90, "🥛"),
        ("Dental Chews",          "Treat", 110, "🦷"),
        ("Salmon Crackers",       "Treat",  95, "🐟"),
        ("Duck Jerky",            "Treat",  95, "🦆"),
        ("Apple Carrot Bites",    "Treat",  50, "🥕"),
        ("Banana Training Treats","Treat",  60, "🍌"),
    ]
    stock_range = {"Coffee": (15, 60), "Pastry": (3, 18), "Treat": (8, 40)}
    product_ids = {}
    for name, category, price, emoji in demo_products:
        existing = cursor.execute(
            "SELECT product_id FROM products WHERE name = ?", (DEMO_PREFIX + name,)).fetchone()
        if existing:
            product_ids[name] = existing["product_id"]
        else:
            lo, hi = stock_range[category]
            stock = random.randint(lo, hi)
            cursor.execute(
                "INSERT INTO products (category, name, price, stock, emoji, status) "
                "VALUES (?, ?, ?, ?, ?, 'available')",
                (category, DEMO_PREFIX + name, price, stock, emoji))
            product_ids[name] = cursor.lastrowid

    # Force a few low-stock and one out-of-stock item so the badges render
    for low_name in ("Chocolate Donut", "Fish Skins", "Apple Carrot Bites"):
        if low_name in product_ids:
            cursor.execute("UPDATE products SET stock = 3 WHERE product_id = ?",
                           (product_ids[low_name],))
    if "Glazed Donut" in product_ids:
        cursor.execute("UPDATE products SET stock = 0 WHERE product_id = ?",
                       (product_ids["Glazed Donut"],))

    # ---------- appointments ----------
    today = datetime.date.today()
    demo_appointments = [
        # (pet, type, breed, age, owner, phone, service_idx, days_from_today, time, notes)
        ("Cooper",  "Dog", "Golden Retriever", "3 years",  "Hannah Reyes",   "+63 917 555 0101", 0, 0, "09:00", "Loves the slipper biscuits — give one after the bath."),
        ("Mochi",   "Cat", "British Shorthair","2 years",  "Jonas Cruz",     "+63 917 555 0102", 1, 0, "10:30", "Anxious around dryers — use low heat."),
        ("Bingo",   "Dog", "Beagle",          "5 years",  "Pat Santos",     "+63 917 555 0103", 2, 1, "11:00", ""),
        ("Luna",    "Cat", "Persian",         "4 years",  "Andrea Lim",     "+63 917 555 0104", 0, 2, "13:00", "First visit. Be gentle."),
        ("Rocky",   "Dog", "Shih Tzu",        "6 years",  "Mark Villanueva","+63 917 555 0105", 5, 0, "14:15", "Sensitive stomach — skip the treats."),
        ("Panda",   "Dog", "Border Collie",   "1 year",   "Trisha Garcia",  "+63 917 555 0106", 3, 0, "15:00", "Very energetic. Needs the longer walk."),
        ("Toffee",  "Cat", "Maine Coon",      "3 years",  "Rico Mendoza",   "+63 917 555 0107", 4, 3, "16:30", "Owner will pick up at 17:00."),
        ("Biscuit", "Dog", "Pomeranian",      "7 years",  "Lia Aquino",     "+63 917 555 0108", 6, 0, "09:30", "Re-booking for full grooming."),
        ("Olive",   "Cat", "Ragdoll",         "2 years",  "Bryan Torres",   "+63 917 555 0109", 7, 1, "11:15", ""),
        ("Spud",    "Dog", "French Bulldog",  "4 years",  "Nina Velasco",   "+63 917 555 0110", 1, 4, "14:00", "Brachycephalic — short breaks every 10 min."),
    ]
    for (pet, ptype, breed, age, owner, phone, svc_idx, days, time_str, notes) in demo_appointments:
        existing = cursor.execute(
            "SELECT appointment_id FROM appointments WHERE pet_name = ? AND appt_date = ?",
            (DEMO_PREFIX + pet, (today + datetime.timedelta(days=days)).isoformat())).fetchone()
        if existing: continue
        cursor.execute(
            """INSERT INTO appointments
               (pet_name, pet_type, breed, pet_age, owner_name, phone,
                service_id, appt_date, appt_time, status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
            (DEMO_PREFIX + pet, ptype, breed, age, owner, phone,
             service_ids[svc_idx],
             (today + datetime.timedelta(days=days)).isoformat(),
             time_str, notes))

    # Flip a couple of statuses for variety
    cursor.execute("""UPDATE appointments SET status = 'completed'
                      WHERE pet_name = ?""", (DEMO_PREFIX + "Biscuit",))
    cursor.execute("""UPDATE appointments SET status = 'cancelled'
                      WHERE pet_name = ?""", (DEMO_PREFIX + "Mochi",))

    # ---------- past orders ----------
    price_lookup = {n: p for n, c, p, e in demo_products}
    demo_past_orders = [
        # (items, customer, payment_method, days_ago, hour)
        ([("Espresso", 1), ("Almond Croissant", 1)],                            "Hannah Reyes", "cash",  0,  9),
        ([("Cappuccino", 2), ("Chocolate Donut", 2)],                            None,          "gcash", 0, 10),
        ([("Caramel Macchiato", 1), ("Cinnamon Roll", 1), ("Chicken Jerky", 1)], "Jonas Cruz", "card",  0, 11),
        ([("Cold Brew", 3), ("Blueberry Muffin", 3)],                           "Pat Santos",   "cash",  0, 12),
        ([("Matcha Latte", 1), ("Pain au Chocolat", 1), ("Pumpkin Biscuits", 1)], None,        "cash",  0, 13),
        ([("Flat White", 2), ("Tiramisu Cup", 1), ("Dental Chews", 1)],         "Mark Villanueva","gcash", 1, 10),
        ([("Mocha", 1), ("Banana Bread Slice", 1)],                              "Walk-in",     "cash",  1, 11),
        ([("Spanish Latte", 2), ("Cheese Danish", 2)],                           "Trisha Garcia","card",  1, 14),
        ([("Americano", 3), ("Apple Turnover", 1)],                              None,          "cash",  2,  8),
        ([("Vanilla Latte", 1), ("Cheesecake Slice", 1), ("Fish Skins", 2)],    "Rico Mendoza","cash",  2, 15),
    ]
    if not cursor.execute(
        "SELECT 1 FROM orders WHERE order_no LIKE 'ORD-DEMO-%'").fetchone():
        now = datetime.datetime.now()
        for i, (items, customer, method, days_ago, hour) in enumerate(demo_past_orders):
            subtotal = sum(price_lookup[n] * q for n, q in items)
            total    = round(subtotal * 1.08, 2)
            paid     = total if method != "cash" else total + random.choice([0, 5, 10, 20])
            change   = round(paid - total, 2)
            order_dt = now - datetime.timedelta(days=days_ago)
            order_dt = order_dt.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)
            order_no = "ORD-DEMO-{:03d}".format(i + 1)
            cursor.execute(
                """INSERT INTO orders
                   (order_no, customer_name, total_amount, payment_method, amount_paid, change_amount, order_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_no, customer, total, method, paid, change, order_dt))
            order_id = cursor.lastrowid
            for name, qty in items:
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                    (order_id, product_ids[name], qty, price_lookup[name]))

    conn.commit()
    conn.close()

    print("=" * 60)
    print("  Brewskers DB ready")
    print("=" * 60)
    print()
    print("  Demo staff logins (password in parentheses):")
    print("    admin   admin@brewskers.test   (BrewskersAdmin!)")
    print("    staff   francis@brewskers.test (DemoStaff#1)")
    print("    staff   kyla@brewskers.test    (DemoStaff#2)")
    print("    staff   miguel@brewskers.test  (DemoStaff#3)")
    print()
    print("  All demo rows are prefixed with '[DEMO]' so they can be")
    print("  identified and removed later without affecting real data.")

if __name__ == "__main__":
    setup()