# Brewskers demo data generator
# Builds realistic sample records for demonstrations and testing.
# Writes one CSV per table into sample-data plus a single ZIP that the
# Import All feature accepts.
#
# Run with: py scripts/make_demo_data.py
# Import with: Admin, Data management, Import all (choose the ZIP)
#
# The data is generated with a fixed random seed so every run produces the
# exact same files. Dates are relative to today so reports and the
# schedule always have data to show.

import csv
import datetime
import io
import os
import random
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "sample-data")

rng = random.Random(20261110)

# Demo orders were placed while the store charged 8 percent tax, so their
# receipts keep that historical rate. The store profile below sets the
# current rate to 12 percent, which new orders at the demo will use. That
# difference shows the tax snapshot feature nicely.
TAX = 0.08
TAX_PERCENT = 8.0

PRODUCTS = [
    # name, category, price, stock
    ("Espresso", "Coffee", 90, 22),
    ("Americano", "Coffee", 110, 18),
    ("Cappuccino", "Coffee", 130, 25),
    ("Caffe Latte", "Coffee", 130, 14),
    ("Caramel Macchiato", "Coffee", 150, 20),
    ("Mocha", "Coffee", 140, 12),
    ("Flat White", "Coffee", 135, 9),
    ("Cold Brew", "Coffee", 145, 16),
    ("Matcha Latte", "Coffee", 155, 8),
    ("Spanish Latte", "Coffee", 150, 11),
    ("Butter Croissant", "Pastry", 85, 3),
    ("Pain au Chocolat", "Pastry", 95, 7),
    ("Cinnamon Roll", "Pastry", 100, 12),
    ("Banana Bread", "Pastry", 75, 20),
    ("Blueberry Muffin", "Pastry", 80, 15),
    ("Chocolate Muffin", "Pastry", 80, 10),
    ("Tiramisu Slice", "Pastry", 140, 6),
    ("Cheesecake", "Pastry", 145, 5),
    ("Chocolate Cookie", "Pastry", 60, 30),
    ("Oatmeal Cookie", "Pastry", 60, 25),
    ("Pup-cchino", "Pet Treats", 60, 18),
    ("Bacon Bites", "Pet Treats", 75, 22),
    ("Chicken Jerky", "Pet Treats", 90, 14),
    ("Salmon Strips", "Pet Treats", 95, 4),
    ("Peanut Butter Cookie", "Pet Treats", 70, 9),
    ("Pumpkin Biscuit", "Pet Treats", 65, 12),
    ("Catnip Cookie", "Pet Treats", 55, 2),
    ("Tuna Treat", "Pet Treats", 70, 16),
    ("Yogurt Drop", "Pet Treats", 60, 8),
    ("Apple Chew", "Pet Treats", 50, 1),
]

SERVICES = [
    # name, price, duration, active
    ("Bath & Brush", 350, 45, 1),
    ("Full Groom", 850, 90, 1),
    ("Nail Trim", 150, 15, 1),
    ("Teeth Brushing", 200, 20, 1),
    ("Vet Checkup", 500, 30, 1),
    ("Vaccination", 450, 20, 1),
    ("Flea Treatment", 400, 30, 1),
    ("Pet Spa Package", 1500, 120, 1),
]

CUSTOMERS = [
    "Maria Santos", "Juan Dela Cruz", "Angela Reyes", "Miguel Cruz",
    "Sofia Garcia", "Rafael Lim", "Isabella Torres", "Andres Ramos",
    "Liwayway Bautista", "Paolo Mendoza", "Camille Villanueva", "Jomar Aquino",
    "Bianca Flores", "Enrique Navarro", "Trisha Ocampo", "Lorenzo Padilla",
    "Mika Salazar", "Diego Aguilar",
]

# Days covered: the past two weeks through today.
TODAY = datetime.date.today()
DAYS = [TODAY - datetime.timedelta(days=offset) for offset in range(13, -1, -1)]


def write_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)


def build_orders():
    """Return orders rows and matching order_items rows."""
    orders = []
    order_items = []

    for day in DAYS:
        per_day = rng.choice([2, 3, 3, 4])
        for seq in range(1, per_day + 1):
            order_no = f"ORD-{day:%y%m%d}-{seq:03d}"
            hour = rng.randint(8, 19)
            minute = rng.choice([0, 15, 30, 45])
            placed_at = f"{day.isoformat()} {hour:02d}:{minute:02d}:00"

            lines = rng.sample(PRODUCTS, rng.randint(1, 4))
            subtotal = 0
            for name, _category, price, _stock in lines:
                qty = rng.randint(1, 3)
                subtotal += price * qty
                order_items.append(
                    [order_no, name, qty, f"{price:.2f}"]
                )

            total = round(subtotal * (1 + TAX), 2)

            method = rng.choices(["cash", "gcash", "card"], [60, 25, 15])[0]
            if method == "cash":
                paid = ((int(total) // 100) + 1) * 100
                change = round(paid - total, 2)
            else:
                paid = total
                change = 0

            # Today keeps a few orders queued for the Queued orders page.
            if day == TODAY:
                status = "queued" if seq <= 3 else "completed"
            elif day in (DAYS[2], DAYS[7], DAYS[11]):
                status = "cancelled" if seq == per_day else "completed"
            else:
                status = "completed"

            if rng.random() < 0.55:
                customer = rng.choice(CUSTOMERS)
            else:
                customer = ""

            if status == "cancelled":
                orders.append(
                    [order_no, customer, f"{total:.2f}", method, "", "", status, placed_at, TAX_PERCENT]
                )
            else:
                orders.append(
                    [order_no, customer, f"{total:.2f}", method, f"{paid:.2f}",
                     f"{change:.2f}", status, placed_at, TAX_PERCENT]
                )

    return orders, order_items


APPOINTMENTS = [
    # service, pet, type, breed, age, owner, phone, date offset, time, status
    ("Bath & Brush", "Mochi", "Cat", "Persian", "2", "Bianca Flores", "09171234501", -10, "09:30", "completed"),
    ("Full Groom", "Bruno", "Dog", "Aspin", "3", "Carlo Reyes", "09171234502", -8, "10:00", "completed"),
    ("Nail Trim", "Pepper", "Cat", "Siamese", "1", "Mika Salazar", "09171234503", -5, "14:00", "completed"),
    ("Vet Checkup", "Max", "Dog", "Beagle", "4", "Angela Reyes", "09171234504", -3, "11:00", "completed"),
    ("Teeth Brushing", "Luna", "Cat", "Puspin", "2", "Paolo Mendoza", "09171234505", -2, "15:30", "completed"),
    ("Flea Treatment", "Chico", "Cat", "Siamese", "3", "Trisha Ocampo", "09171234506", -7, "13:15", "cancelled"),
    ("Pet Spa Package", "Coco", "Dog", "Shih Tzu", "5", "Sofia Garcia", "09171234507", 5, "09:45", "cancelled"),
    ("Bath & Brush", "Rocky", "Dog", "Golden Retriever", "2", "Miguel Cruz", "09171234508", 2, "09:00", "scheduled"),
    ("Full Groom", "Nala", "Cat", "Bengal", "1", "Isabella Torres", "09171234509", 3, "10:30", "scheduled"),
    ("Vaccination", "Simba", "Cat", "Tabby", "7 months", "Rafael Lim", "09171234510", 4, "13:00", "scheduled"),
    ("Vet Checkup", "Bantay", "Dog", "Aspin", "6", "Juan Dela Cruz", "09171234511", 7, "16:00", "scheduled"),
    ("Bath & Brush", "Milo", "Dog", "Pomeranian", "8 months", "Camille Villanueva", "09171234512", 9, "11:15", "scheduled"),
]


def build_appointments():
    rows = []
    notes = [
        "", "", "Sensitive skin, use gentle shampoo",
        "First visit", "", "Owner will wait in the cafe",
        "Prefers afternoon slots", "",
    ]
    for index, (service, pet, pet_type, breed, age, owner, phone, offset,
                appt_time, status) in enumerate(APPOINTMENTS):
        day = TODAY + datetime.timedelta(days=offset)
        rows.append([
            service, pet, pet_type, breed, age, owner, phone,
            day.isoformat(), appt_time, status, notes[index % len(notes)],
        ])
    return rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    write_csv(
        os.path.join(OUT_DIR, "products.csv"),
        ["name", "category", "price", "stock"],
        [[n, c, f"{p:.2f}", s] for n, c, p, s in PRODUCTS],
    )

    write_csv(
        os.path.join(OUT_DIR, "services.csv"),
        ["name", "price", "duration", "active"],
        [[n, f"{p:.2f}", d, a] for n, p, d, a in SERVICES],
    )

    orders, order_items = build_orders()
    write_csv(
        os.path.join(OUT_DIR, "orders.csv"),
        ["order_no", "customer_name", "total_amount", "payment_method",
         "amount_paid", "change_amount", "status", "order_date", "tax_rate"],
        orders,
    )
    write_csv(
        os.path.join(OUT_DIR, "order_items.csv"),
        ["order_no", "product_name", "quantity", "price"],
        order_items,
    )

    write_csv(
        os.path.join(OUT_DIR, "appointments.csv"),
        ["service_name", "pet_name", "pet_type", "breed", "pet_age",
         "owner_name", "phone", "appt_date", "appt_time", "status", "notes"],
        build_appointments(),
    )

    # The store profile so imported demo data also carries the settings.
    write_csv(
        os.path.join(OUT_DIR, "store_profile.csv"),
        ["store_name", "address", "phone", "email", "tax_rate", "low_stock_limit"],
        [[
            "Brewskers Pet Cafe",
            "123 Sample St, Laguna",
            "0900-000-0000",
            "hello@brewskers.example",
            "12.0",
            "5",
        ]],
    )

    # One ZIP holding every CSV, ready for the Import All feature.
    zip_path = os.path.join(OUT_DIR, "brewskers-demo-data.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("products.csv", "services.csv", "orders.csv",
                     "order_items.csv", "appointments.csv", "store_profile.csv"):
            zf.write(os.path.join(OUT_DIR, name), name)

    print(f"Sample data written to {OUT_DIR}")
    print(f"  products: {len(PRODUCTS)}")
    print(f"  services: {len(SERVICES)}")
    print(f"  orders: {len(orders)} ({sum(1 for o in orders if o[6] == 'queued')} queued, "
          f"{sum(1 for o in orders if o[6] == 'cancelled')} cancelled)")
    print(f"  order items: {len(order_items)}")
    print(f"  appointments: {len(APPOINTMENTS)}")
    print(f"  zip: {zip_path}")


if __name__ == "__main__":
    main()
