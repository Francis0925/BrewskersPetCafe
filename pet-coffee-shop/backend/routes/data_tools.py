# Brewskers data tools routes
# CSV and SQL import and export for all data, plus admin data reset

import csv
import datetime
import io
import os
import re
import sqlite3
import zipfile

from flask import Response, jsonify, render_template, request, send_file

from backend.activity import record_activity
from backend.auth import app, connect_db
from backend.csv_utils import (
    csv_bytes,
    csv_download,
    parse_csv_text,
    parse_csv_upload,
    validate_product_csv_row,
    validate_service_csv_row,
)
from backend.database import get_database_path, migrate_db
from backend.errors import InvalidRecordError
from backend.helpers import query, run
from backend.models import StoreSettings
from backend.permissions import admin_required
from backend.pos_state import reset_all


EXPORT_ALL_TABLES = {
    "products": ["category", "name", "price", "stock", "status", "image"],
    "services": ["name", "price", "duration", "active"],
    "orders": ["order_no", "customer_name", "total_amount", "payment_method", "amount_paid", "change_amount", "status", "tax_rate"],
    "order_items": ["order_no", "product_name", "quantity", "price"],
    "appointments": ["pet_name", "pet_type", "breed", "pet_age", "owner_name", "phone", "service_name", "appt_date", "appt_time", "status", "notes"],
    "store_profile": ["store_name", "address", "phone", "email", "tax_rate", "low_stock_limit"],
}


def _export_all_rows():
    products = query("SELECT category, name, price, stock, status, COALESCE(image, '') AS image FROM products ORDER BY category, name")
    services = query("SELECT name, price, duration, active FROM services ORDER BY name")
    orders = query(
        "SELECT order_no, COALESCE(customer_name, '') AS customer_name, total_amount, payment_method, "
        "COALESCE(amount_paid, '') AS amount_paid, COALESCE(change_amount, '') AS change_amount, "
        "COALESCE(status, 'completed') AS status, COALESCE(tax_rate, 8.0) AS tax_rate "
        "FROM orders ORDER BY order_date, order_id"
    )
    order_items = query(
        "SELECT o.order_no AS order_no, COALESCE(p.name, 'Removed product') AS product_name, "
        "oi.quantity AS quantity, oi.price AS price FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id LEFT JOIN products p ON p.product_id = oi.product_id "
        "ORDER BY o.order_id, oi.item_id"
    )
    appointments = query(
        "SELECT a.pet_name, a.pet_type, COALESCE(a.breed, '') AS breed, COALESCE(a.pet_age, '') AS pet_age, "
        "a.owner_name, a.phone, s.name AS service_name, a.appt_date, a.appt_time, a.status, COALESCE(a.notes, '') AS notes "
        "FROM appointments a JOIN services s ON s.service_id = a.service_id ORDER BY a.appt_date, a.appt_time"
    )
    store_profile = query("SELECT store_name, COALESCE(address, '') AS address, COALESCE(phone, '') AS phone, COALESCE(email, '') AS email, COALESCE(tax_rate, 12.0) AS tax_rate, COALESCE(low_stock_limit, 5) AS low_stock_limit FROM store_profile")
    return {
        "products": products,
        "services": services,
        "orders": orders,
        "order_items": order_items,
        "appointments": appointments,
        "store_profile": store_profile,
    }


# Data maintenance actions shown on the admin data page. Each entry keeps
# the dialog text, the SQL statements it runs, and the query that counts
# the records it would touch. confirm_word marks the permanent deletions
# and bulk resets that also need the admin to type that word before the
# server accepts the request. Actions without a confirm_word only hide or
# flag records, so the dialog alone is enough confirmation.
MAINTENANCE_ACTIONS = {
    # Inventory and catalog maintenance.
    "reset_stock": {
        "title": "Reset all product stock",
        "summary": "Set the stock of every product to zero without deleting product records.",
        "details": "Product records, prices and pictures are kept, but every stock count becomes zero, so nothing can be sold on the POS until items are restocked. Orders and sales reports are not changed.",
        "button": "Reset stock",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM products",
        "count_noun": "products",
        "related_sql": None,
        "related_noun": "",
        "steps": ["UPDATE products SET stock = 0"],
        "result": "Stock reset to zero on {n} products",
    },
    "deactivate_products": {
        "title": "Deactivate all products",
        "summary": "Make all products unavailable for POS transactions while keeping their records.",
        "details": "Products are hidden from the POS and the inventory page, but their records stay in the database with prices, stock and pictures. Importing the products CSV again makes them available again.",
        "button": "Deactivate products",
        "confirm_word": None,
        "count_sql": "SELECT COUNT(*) FROM products WHERE status != 'hidden'",
        "count_noun": "products",
        "related_sql": None,
        "related_noun": "",
        "steps": ["UPDATE products SET status = 'hidden' WHERE status != 'hidden'"],
        "result": "Deactivated {n} products",
    },
    "deactivate_services": {
        "title": "Deactivate all services",
        "summary": "Make every pet care service unavailable for new appointments without deleting it.",
        "details": "Services stop appearing on the booking form, but their records stay with prices and durations. Existing appointments are kept and still show their service. Importing the services CSV again makes them bookable again.",
        "button": "Deactivate services",
        "confirm_word": None,
        "count_sql": "SELECT COUNT(*) FROM services WHERE active != 0",
        "count_noun": "services",
        "related_sql": None,
        "related_noun": "",
        "steps": ["UPDATE services SET active = 0 WHERE active != 0"],
        "result": "Deactivated {n} services",
    },
    # Business record maintenance.
    "clear_appointments": {
        "title": "Clear appointment history",
        "summary": "Permanently remove all appointment records and scheduled guest information.",
        "details": "Every appointment is deleted, whether it is scheduled, completed or cancelled. Pet names, owner names, phone numbers and visit notes are gone for good. The services themselves are kept.",
        "button": "Clear appointments",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM appointments",
        "count_noun": "appointments",
        "related_sql": None,
        "related_noun": "",
        "steps": ["DELETE FROM appointments"],
        "result": "Permanently deleted {n} appointments",
    },
    "clear_cancelled_appointments": {
        "title": "Clear cancelled appointments",
        "summary": "Permanently remove cancelled appointment records.",
        "details": "Only appointments marked as cancelled are deleted. Scheduled and completed appointments are kept, and the scheduler keeps working as before.",
        "button": "Clear cancelled",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'",
        "count_noun": "cancelled appointments",
        "related_sql": None,
        "related_noun": "",
        "steps": ["DELETE FROM appointments WHERE status = 'cancelled'"],
        "result": "Permanently deleted {n} cancelled appointments",
    },
    "clear_completed_appointments": {
        "title": "Clear completed appointments",
        "summary": "Permanently remove completed appointment records.",
        "details": "Only appointments marked as completed are deleted. Scheduled and cancelled appointments are kept, and the scheduler keeps working as before.",
        "button": "Clear completed",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM appointments WHERE status = 'completed'",
        "count_noun": "completed appointments",
        "related_sql": None,
        "related_noun": "",
        "steps": ["DELETE FROM appointments WHERE status = 'completed'"],
        "result": "Permanently deleted {n} completed appointments",
    },
    "clear_orders": {
        "title": "Clear order history",
        "summary": "Permanently remove all orders, order items, sales totals, and receipt history.",
        "details": "Orders and the order lines linked to them are deleted together, so receipts can no longer be reprinted and sales reports start from zero. Products and their stock are not changed.",
        "button": "Clear orders",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM orders",
        "count_noun": "orders",
        "related_sql": "SELECT COUNT(*) FROM order_items",
        "related_noun": "order lines",
        "steps": [
            "DELETE FROM order_items",
            "DELETE FROM orders",
        ],
        "result": "Permanently deleted {n} orders",
    },
    "clear_customers": {
        "title": "Clear customer records",
        "summary": "Remove customer names from orders without deleting the orders.",
        "details": "Customer names are removed from order records, but each order, its totals and its receipts stay for reporting. Appointments keep their owner names because those bookings still need them.",
        "button": "Clear customers",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM orders WHERE customer_name IS NOT NULL",
        "count_noun": "orders with a customer name",
        "related_sql": None,
        "related_noun": "",
        "steps": ["UPDATE orders SET customer_name = NULL WHERE customer_name IS NOT NULL"],
        "result": "Removed customer names from {n} orders",
    },
    # System activity maintenance.
    "clear_activity": {
        "title": "Clear activity logs",
        "summary": "Permanently remove all activity log entries.",
        "details": "Every recorded staff action is deleted. One new entry describing this maintenance action is written afterwards, so the log still shows who cleared it. Staff accounts and sessions are not touched.",
        "button": "Clear activity",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM activity_log",
        "count_noun": "activity log entries",
        "related_sql": None,
        "related_noun": "",
        "steps": ["DELETE FROM activity_log"],
        "result": "Permanently deleted {n} activity log entries",
    },
    "clear_logins": {
        "title": "Clear login history",
        "summary": "Remove historical login records without affecting active sessions.",
        "details": "Successful and failed login entries are removed from the activity log. Other activity entries are kept. Staff accounts, active sessions and logged in staff are not affected.",
        "button": "Clear logins",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM activity_log WHERE action LIKE 'login%'",
        "count_noun": "login history entries",
        "related_sql": None,
        "related_noun": "",
        "steps": ["DELETE FROM activity_log WHERE action LIKE 'login%'"],
        "result": "Permanently deleted {n} login history entries",
    },
    "clear_archived": {
        "title": "Clear archived records",
        "summary": "Permanently remove archived records.",
        "details": "Hidden products are deleted for good, together with the order lines linked to them, so receipts for those orders lose those lines. Orders keep their totals and sales reports stay correct. Available products are not touched.",
        "button": "Clear archived",
        "confirm_word": "DELETE",
        "count_sql": "SELECT COUNT(*) FROM products WHERE status = 'hidden'",
        "count_noun": "archived products",
        "related_sql": "SELECT COUNT(*) FROM order_items WHERE product_id IN (SELECT product_id FROM products WHERE status = 'hidden')",
        "related_noun": "order lines linked to them",
        "steps": [
            "DELETE FROM order_items WHERE product_id IN (SELECT product_id FROM products WHERE status = 'hidden')",
            "DELETE FROM products WHERE status = 'hidden'",
        ],
        "result": "Permanently deleted {n} archived products",
    },
}


def _maintenance_dialog_specs():
    """Dialog metadata for the page, without any SQL in it."""
    return {
        key: {
            "title": spec["title"],
            "summary": spec["summary"],
            "details": spec["details"],
            "button": spec["button"],
            "confirm_word": spec["confirm_word"],
            "count_noun": spec["count_noun"],
            "related_noun": spec["related_noun"],
        }
        for key, spec in MAINTENANCE_ACTIONS.items()
    }


@app.get("/admin/data")
@admin_required
def admin_data(user):
    # Row counts for the overview strip at the top of the page.
    counts = {}
    for table in (
        "products", "services", "orders", "order_items",
        "appointments", "users", "activity_log",
    ):
        counts[table] = query(
            f"SELECT COUNT(*) AS n FROM {table}",
            one=True,
            default={"n": 0},
        )["n"]

    db_path = get_database_path()
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    backups = (
        sorted(f for f in os.listdir(backup_dir) if f.endswith(".db"))
        if os.path.exists(backup_dir)
        else []
    )

    return render_template(
        "data_tools.html",
        title="Data management",
        active="admin",
        user=user,
        exports={"products": "Products", "services": "Services", "orders": "Orders", "appointments": "Appointments"},
        counts=counts,
        db_size=db_size,
        backup_count=len(backups),
        last_backup=backups[-1] if backups else None,
        maintenance_actions=_maintenance_dialog_specs(),
    )


@app.get("/api/admin/export/all.zip")
@admin_required
def export_all_csv_zip(user):
    rows_by_table = _export_all_rows()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for table, headers in EXPORT_ALL_TABLES.items():
            zf.writestr(f"{table}.csv", csv_bytes(headers, rows_by_table[table]))
    buffer.seek(0)
    record_activity(user_id=user["user_id"], action="all_exported", description="Exported all data as CSV ZIP", entity_type="system")
    return Response(buffer.getvalue(), mimetype="application/zip", headers={"Content-Disposition": "attachment; filename=brewskers-all-data.zip"})


@app.get("/api/admin/export/all.sql")
@admin_required
def export_all_sql(user):
    db = connect_db()
    try:
        lines = list(db.iterdump())
    finally:
        db.close()
    record_activity(user_id=user["user_id"], action="all_sql_exported", description="Exported all data as SQL file", entity_type="system")
    return Response("\n".join(lines), mimetype="application/sql", headers={"Content-Disposition": "attachment; filename=brewskers-all-data.sql"})


@app.get("/api/admin/export/all.db")
@admin_required
def export_all_db(user):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(os.path.dirname(get_database_path()), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, f"brewskers-export-{stamp}.db")
    source = sqlite3.connect(get_database_path())
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()
    record_activity(user_id=user["user_id"], action="all_db_exported", description="Exported all data as database file", entity_type="system")
    return send_file(target, as_attachment=True, download_name=f"brewskers-all-data-{stamp}.db")


@app.get("/api/admin/export/<export_type>")
@admin_required
def export_admin_data(user, export_type):
    if export_type == "products":
        products = query("SELECT category, name, price, stock, COALESCE(image, '') AS image FROM products WHERE status != 'hidden' ORDER BY category, name")
        response = csv_download("brewskers-products.csv", ["name", "category", "price", "stock", "image"], products)
        record_activity(user_id=user["user_id"], action="products_exported", description=f"Exported {len(products)} products to CSV", entity_type="product")
        return response
    if export_type == "services":
        services = query("SELECT name, price, duration, active FROM services ORDER BY name")
        response = csv_download("brewskers-services.csv", ["name", "price", "duration", "active"], services)
        record_activity(user_id=user["user_id"], action="services_exported", description=f"Exported {len(services)} services to CSV", entity_type="service")
        return response
    if export_type == "orders":
        orders = _export_all_rows()["orders"]
        response = csv_download("brewskers-orders.csv", ["order_no", "customer_name", "total_amount", "payment_method", "amount_paid", "change_amount", "status"], orders)
        record_activity(user_id=user["user_id"], action="orders_exported", description=f"Exported {len(orders)} orders to CSV", entity_type="order")
        return response
    if export_type == "appointments":
        appointments = _export_all_rows()["appointments"]
        response = csv_download("brewskers-appointments.csv", ["pet_name", "pet_type", "breed", "pet_age", "owner_name", "phone", "service_name", "appt_date", "appt_time", "status", "notes"], appointments)
        record_activity(user_id=user["user_id"], action="appointments_exported", description=f"Exported {len(appointments)} appointments to CSV", entity_type="appointment")
        return response
    return jsonify(ok=False, error="Unknown export type"), 404


@app.post("/api/admin/import/preview")
@admin_required
def preview_admin_import(user):
    entity_type = request.form.get("entity_type", "").strip().lower()
    if entity_type not in {"products", "services"}:
        return jsonify(ok=False, error="Invalid record type"), 400
    upload = request.files.get("file")
    try:
        if entity_type == "products":
            reader, headers = parse_csv_upload(upload, ["name", "category", "price", "stock"])
            validator = validate_product_csv_row
        else:
            reader, headers = parse_csv_upload(upload, ["name", "price", "duration", "active"])
            validator = validate_service_csv_row
        valid_count = 0
        errors = []
        for row_number, row in enumerate(reader, start=2):
            try:
                validator(row, headers)
                valid_count += 1
            except ValueError as error:
                errors.append({"row": row_number, "message": str(error)})
        return jsonify(ok=True, entity_type=entity_type, valid_count=valid_count, error_count=len(errors), errors=errors)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400


@app.post("/api/admin/import/confirm")
@admin_required
def confirm_admin_import(user):
    entity_type = request.form.get("entity_type", "").strip().lower()
    if entity_type not in {"products", "services"}:
        return jsonify(ok=False, error="Invalid record type"), 400
    upload = request.files.get("file")
    try:
        if entity_type == "products":
            reader, headers = parse_csv_upload(upload, ["name", "category", "price", "stock"])
            validator = validate_product_csv_row
        else:
            reader, headers = parse_csv_upload(upload, ["name", "price", "duration", "active"])
            validator = validate_service_csv_row
        rows = [validator(row, headers) for row in reader]
        if not rows:
            raise ValueError("The CSV contains no data rows")
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    db = connect_db()
    cursor = db.cursor()
    try:
        if entity_type == "products":
            for item in rows:
                existing = cursor.execute("SELECT product_id FROM products WHERE name = ? ORDER BY product_id LIMIT 1", (item["name"],)).fetchone()
                if existing:
                    cursor.execute("UPDATE products SET category = ?, price = ?, stock = ?, status = 'available' WHERE product_id = ?", (item["category"], item["price"], item["stock"], existing["product_id"]))
                else:
                    cursor.execute("INSERT INTO products (category, name, price, stock, status) VALUES (?, ?, ?, ?, 'available')", (item["category"], item["name"], item["price"], item["stock"]))
        else:
            for item in rows:
                existing = cursor.execute("SELECT service_id FROM services WHERE name = ? ORDER BY service_id LIMIT 1", (item["name"],)).fetchone()
                if existing:
                    cursor.execute("UPDATE services SET price = ?, duration = ?, active = ? WHERE service_id = ?", (item["price"], item["duration"], item["active"], existing["service_id"]))
                else:
                    cursor.execute("INSERT INTO services (name, price, duration, active) VALUES (?, ?, ?, ?)", (item["name"], item["price"], item["duration"], item["active"]))
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("CSV import failed")
        return jsonify(ok=False, error="Could not import the CSV"), 500
    finally:
        db.close()
    reset_all()
    record_activity(user_id=user["user_id"], action="csv_imported", description=f"Imported {len(rows)} {entity_type} from CSV", entity_type=entity_type)
    return jsonify(ok=True, imported_count=len(rows))


def _read_zip_csvs(upload):
    if upload is None:
        raise ValueError("Choose a ZIP file")
    if not (upload.filename or "").lower().endswith(".zip"):
        raise ValueError("Only ZIP files are allowed")
    raw = upload.read()
    if not raw:
        raise ValueError("The ZIP file is empty")
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".csv"):
                    files[os.path.basename(name).lower()] = zf.read(name).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeDecodeError):
        raise ValueError("The ZIP file is invalid or not UTF-8")
    return files


@app.post("/api/admin/import/all/preview")
@admin_required
def preview_all_import(user):
    upload = request.files.get("file")
    try:
        files = _read_zip_csvs(upload)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    summary = {}
    errors = []
    for table in ["products.csv", "services.csv", "orders.csv", "order_items.csv", "appointments.csv", "store_profile.csv"]:
        if table not in files:
            summary[table] = {"present": False, "count": 0}
            continue
        rows = list(csv.DictReader(io.StringIO(files[table])))
        summary[table] = {"present": True, "count": len(rows)}
    # Validate products and services rows the same way as single import
    for name, required, validator in [
        ("products.csv", ["name", "category", "price", "stock"], validate_product_csv_row),
        ("services.csv", ["name", "price", "duration", "active"], validate_service_csv_row),
    ]:
        if name in files:
            try:
                reader, headers = parse_csv_text(files[name], required)
                for n, row in enumerate(reader, start=2):
                    try:
                        validator(row, headers)
                    except ValueError as e:
                        errors.append({"file": name, "row": n, "message": str(e)})
            except ValueError as e:
                errors.append({"file": name, "row": 0, "message": str(e)})
    return jsonify(ok=True, summary=summary, errors=errors, error_count=len(errors))


@app.post("/api/admin/import/all/confirm")
@admin_required
def confirm_all_import(user):
    upload = request.files.get("file")
    try:
        files = _read_zip_csvs(upload)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    imported = {}
    db = connect_db()
    cursor = db.cursor()
    try:
        # Products upsert by name
        if "products.csv" in files:
            reader, headers = parse_csv_text(files["products.csv"], ["name", "category", "price", "stock"])
            count = 0
            for row in reader:
                item = validate_product_csv_row(row, headers)
                existing = cursor.execute("SELECT product_id FROM products WHERE name = ? LIMIT 1", (item["name"],)).fetchone()
                if existing:
                    cursor.execute("UPDATE products SET category = ?, price = ?, stock = ?, status = 'available' WHERE product_id = ?", (item["category"], item["price"], item["stock"], existing["product_id"]))
                else:
                    cursor.execute("INSERT INTO products (category, name, price, stock, status) VALUES (?, ?, ?, ?, 'available')", (item["category"], item["name"], item["price"], item["stock"]))
                count += 1
            imported["products"] = count
        # Services upsert by name
        if "services.csv" in files:
            reader, headers = parse_csv_text(files["services.csv"], ["name", "price", "duration", "active"])
            count = 0
            for row in reader:
                item = validate_service_csv_row(row, headers)
                existing = cursor.execute("SELECT service_id FROM services WHERE name = ? LIMIT 1", (item["name"],)).fetchone()
                if existing:
                    cursor.execute("UPDATE services SET price = ?, duration = ?, active = ? WHERE service_id = ?", (item["price"], item["duration"], item["active"], existing["service_id"]))
                else:
                    cursor.execute("INSERT INTO services (name, price, duration, active) VALUES (?, ?, ?, ?)", (item["name"], item["price"], item["duration"], item["active"]))
                count += 1
            imported["services"] = count
        # Orders: skip existing order_no to avoid duplicates
        order_id_by_no = {}
        if "orders.csv" in files:
            reader = csv.DictReader(io.StringIO(files["orders.csv"]))
            count = 0
            for row in reader:
                order_no = (row.get("order_no") or "").strip()
                if not order_no:
                    continue
                existing = cursor.execute("SELECT order_id FROM orders WHERE order_no = ? LIMIT 1", (order_no,)).fetchone()
                if existing:
                    order_id_by_no[order_no] = existing["order_id"]
                    continue
                try:
                    total = float(row.get("total_amount") or 0)
                except ValueError:
                    continue
                status = (row.get("status") or "completed").strip().lower()
                if status not in ("queued", "completed", "cancelled"):
                    status = "queued"
                # Optional order_date column, so imported orders keep their
                # original day instead of all landing on today. Empty or
                # invalid values fall back to the table default, which is now.
                order_date = (row.get("order_date") or "").strip()
                try:
                    datetime.datetime.fromisoformat(order_date)
                except ValueError:
                    order_date = None
                # Optional tax rate snapshot, so reprinted receipts keep the
                # rate that was actually charged. Missing or invalid values
                # fall back to 8.0, the rate used before this column existed.
                try:
                    order_tax_rate = float(row.get("tax_rate"))
                    if not 0 <= order_tax_rate <= 100:
                        order_tax_rate = 8.0
                except (TypeError, ValueError):
                    order_tax_rate = 8.0
                cursor.execute(
                    "INSERT INTO orders (order_no, customer_name, total_amount, payment_method, amount_paid, change_amount, status, order_date, tax_rate) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?)",
                    (order_no, (row.get("customer_name") or "Walk-in").strip() or "Walk-in", total, (row.get("payment_method") or "cash").strip() or "cash", row.get("amount_paid") or None, row.get("change_amount") or None, status, order_date, order_tax_rate),
                )
                order_id_by_no[order_no] = cursor.lastrowid
                count += 1
            imported["orders"] = count
        # Order items: only for orders imported or already known by order_no in this file
        if "order_items.csv" in files:
            reader = csv.DictReader(io.StringIO(files["order_items.csv"]))
            count = 0
            for row in reader:
                order_no = (row.get("order_no") or "").strip()
                order_id = order_id_by_no.get(order_no)
                if not order_id:
                    # Try existing in DB
                    existing = cursor.execute("SELECT order_id FROM orders WHERE order_no = ? LIMIT 1", (order_no,)).fetchone()
                    order_id = existing["order_id"] if existing else None
                if not order_id:
                    continue
                product_name = (row.get("product_name") or "").strip()
                product = cursor.execute("SELECT product_id FROM products WHERE name = ? LIMIT 1", (product_name,)).fetchone()
                if not product:
                    continue
                try:
                    qty = int(row.get("quantity") or 0)
                    price = float(row.get("price") or 0)
                except ValueError:
                    continue
                cursor.execute("INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)", (order_id, product["product_id"], qty, price))
                count += 1
            imported["order_items"] = count
        # Appointments: insert as new, matching service by name
        if "appointments.csv" in files:
            reader = csv.DictReader(io.StringIO(files["appointments.csv"]))
            count = 0
            for row in reader:
                service_name = (row.get("service_name") or "").strip()
                service = cursor.execute("SELECT service_id FROM services WHERE name = ? LIMIT 1", (service_name,)).fetchone()
                if not service:
                    continue
                if not (row.get("pet_name") and row.get("owner_name") and row.get("phone") and row.get("appt_date") and row.get("appt_time")):
                    continue
                status = (row.get("status") or "scheduled").strip().lower()
                if status not in ("scheduled", "completed", "cancelled"):
                    status = "scheduled"
                cursor.execute(
                    "INSERT INTO appointments (pet_name, pet_type, breed, pet_age, owner_name, phone, service_id, appt_date, appt_time, status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ((row.get("pet_name") or "").strip(), (row.get("pet_type") or "Dog").strip() or "Dog", (row.get("breed") or "").strip(), (row.get("pet_age") or "").strip(), (row.get("owner_name") or "").strip(), (row.get("phone") or "").strip(), service["service_id"], (row.get("appt_date") or "").strip(), (row.get("appt_time") or "").strip(), status, (row.get("notes") or "").strip()),
                )
                count += 1
            imported["appointments"] = count
        # Store profile: update the single profile row when the ZIP has one
        if "store_profile.csv" in files:
            reader = csv.DictReader(io.StringIO(files["store_profile.csv"]))
            row = next(reader, None)
            if row:
                store_name = (row.get("store_name") or "").strip() or "Brewskers"
                current = cursor.execute(
                    "SELECT tax_rate, low_stock_limit FROM store_profile LIMIT 1"
                ).fetchone()
                # Keep the current values when the CSV omits the settings
                # columns or carries something invalid.
                try:
                    profile_tax = float(row.get("tax_rate"))
                    if not 0 <= profile_tax <= 100:
                        raise ValueError
                except (TypeError, ValueError):
                    profile_tax = (
                        float(current["tax_rate"]) if current and current["tax_rate"] is not None else 12.0
                    )
                try:
                    profile_low = int(row.get("low_stock_limit"))
                    if not 0 <= profile_low <= 999:
                        raise ValueError
                except (TypeError, ValueError):
                    profile_low = (
                        int(current["low_stock_limit"]) if current and current["low_stock_limit"] is not None else 5
                    )
                existing = cursor.execute("SELECT store_id FROM store_profile LIMIT 1").fetchone()
                if existing:
                    cursor.execute(
                        "UPDATE store_profile SET store_name = ?, address = ?, phone = ?, email = ?, tax_rate = ?, low_stock_limit = ? WHERE store_id = ?",
                        (store_name, (row.get("address") or "").strip(), (row.get("phone") or "").strip(), (row.get("email") or "").strip(), profile_tax, profile_low, existing["store_id"]),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO store_profile (store_name, address, phone, email, tax_rate, low_stock_limit) VALUES (?, ?, ?, ?, ?, ?)",
                        (store_name, (row.get("address") or "").strip(), (row.get("phone") or "").strip(), (row.get("email") or "").strip(), profile_tax, profile_low),
                    )
                imported["store_profile"] = 1
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Import all failed")
        return jsonify(ok=False, error="Could not import the ZIP file"), 500
    finally:
        db.close()
    reset_all()
    record_activity(user_id=user["user_id"], action="all_imported", description=f"Imported all data from ZIP: {imported}", entity_type="system")
    return jsonify(ok=True, imported=imported)


@app.post("/api/admin/import/database")
@admin_required
def import_database(user):
    """Restore a .db or .sql file. Current DB is backed up first."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(ok=False, error="Choose a .db or .sql file"), 400
    filename = upload.filename.lower()
    if not (filename.endswith(".db") or filename.endswith(".sql")):
        return jsonify(ok=False, error="Only .db or .sql files are allowed"), 400
    # Auto-backup current DB before replacing it
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(os.path.dirname(get_database_path()), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    auto_backup = os.path.join(backup_dir, f"brewskers-before-restore-{stamp}.db")
    source = sqlite3.connect(get_database_path())
    copy = sqlite3.connect(auto_backup)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()
    if filename.endswith(".db"):
        raw = upload.read()
        if not raw:
            return jsonify(ok=False, error="The database file is empty"), 400
        tmp_path = os.path.join(backup_dir, f"restore-{stamp}.db")
        with open(tmp_path, "wb") as f:
            f.write(raw)
        # Verify it is a valid SQLite file with tables
        try:
            test = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
            tables = test.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            test.close()
            if tables == 0:
                os.remove(tmp_path)
                return jsonify(ok=False, error="The database file has no tables"), 400
        except sqlite3.Error:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return jsonify(ok=False, error="The database file is invalid"), 400
        # Replace live DB via backup API from uploaded file
        src = sqlite3.connect(tmp_path)
        dst = sqlite3.connect(get_database_path())
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        os.remove(tmp_path)
    else:
        sql_text = upload.read().decode("utf-8", errors="ignore")
        if not sql_text.strip():
            return jsonify(ok=False, error="The SQL file is empty"), 400
        db = connect_db()
        try:
            db.executescript(sql_text)
            db.commit()
        except Exception:
            db.rollback()
            app.logger.exception("SQL restore failed")
            return jsonify(ok=False, error="Could not restore the SQL file"), 500
        finally:
            db.close()
    # The restored file may come from an older version of the app, so run
    # the startup migrations right away. Without this, a backup without
    # the settings columns would break checkout until the next restart.
    migrate_db()
    reset_all()
    record_activity(user_id=user["user_id"], action="database_restored", description=f"Restored database from {upload.filename}, previous DB backed up", entity_type="system")
    return jsonify(ok=True, auto_backup=os.path.basename(auto_backup))


@app.post("/api/admin/backup")
@admin_required
def create_backup_now(user):
    """Create a dated backup file now and return its name."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(os.path.dirname(get_database_path()), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, f"brewskers-{stamp}.db")
    source = sqlite3.connect(get_database_path())
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()
    record_activity(user_id=user["user_id"], action="backup_created", description=f"Created backup {os.path.basename(target)}", entity_type="system")
    return jsonify(ok=True, backup=os.path.basename(target))


@app.get("/admin/settings")
@admin_required
def settings_page(user):
    profile = query("SELECT * FROM store_profile LIMIT 1", one=True) or {
        "store_name": "Brewskers", "address": "", "phone": "", "email": "",
        "tax_rate": 12.0, "low_stock_limit": 5,
    }
    settings = StoreSettings.from_row(profile)
    db_path = get_database_path()
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    backups = []
    if os.path.exists(backup_dir):
        for name in sorted(f for f in os.listdir(backup_dir) if f.endswith(".db")):
            path = os.path.join(backup_dir, name)
            backups.append(
                {
                    "name": name,
                    "size": os.path.getsize(path) if os.path.exists(path) else 0,
                    "created": datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
                }
            )
    return render_template(
        "settings.html",
        user=user,
        active="admin",
        title="Settings",
        profile=profile,
        settings=settings,
        db_size=db_size,
        backups=backups,
    )


@app.post("/api/admin/settings")
@admin_required
def update_settings(user):
    data = request.get_json(force=True) or {}
    store_name = (data.get("store_name") or "").strip()
    if not store_name:
        return jsonify(ok=False, error="Store name is required"), 400
    existing = query("SELECT store_id FROM store_profile LIMIT 1", one=True)
    if existing:
        run("UPDATE store_profile SET store_name = ?, address = ?, phone = ?, email = ? WHERE store_id = ?", (store_name, (data.get("address") or "").strip(), (data.get("phone") or "").strip(), (data.get("email") or "").strip(), existing["store_id"]))
    else:
        run("INSERT INTO store_profile (store_name, address, phone, email) VALUES (?, ?, ?, ?)", (store_name, (data.get("address") or "").strip(), (data.get("phone") or "").strip(), (data.get("email") or "").strip()))
    record_activity(user_id=user["user_id"], action="settings_updated", description="Updated store profile", entity_type="system")
    return jsonify(ok=True)


@app.post("/api/admin/settings/operations")
@admin_required
def update_operations_settings(user):
    """Save the tax rate and low stock threshold from the settings page."""
    data = request.get_json(force=True) or {}
    try:
        tax_rate = StoreSettings.parse_tax_rate(data.get("tax_rate"))
        low_stock_limit = StoreSettings.parse_low_stock_limit(data.get("low_stock_limit"))
    except InvalidRecordError as error:
        return jsonify(ok=False, error=str(error)), 400

    existing = query("SELECT store_id FROM store_profile LIMIT 1", one=True)
    if existing:
        run(
            "UPDATE store_profile SET tax_rate = ?, low_stock_limit = ? WHERE store_id = ?",
            (float(tax_rate), low_stock_limit, existing["store_id"]),
        )
    else:
        run(
            "INSERT INTO store_profile (store_name, tax_rate, low_stock_limit) VALUES ('Brewskers', ?, ?)",
            (float(tax_rate), low_stock_limit),
        )
    record_activity(
        user_id=user["user_id"],
        action="settings_updated",
        description=f"Updated operations settings, tax {tax_rate} percent, low stock at {low_stock_limit}",
        entity_type="system",
    )
    return jsonify(ok=True, tax_rate=float(tax_rate), low_stock_limit=low_stock_limit)


# Only plain backup filenames are accepted, never paths, so a request can
# never reach a file outside the backups folder.
BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.db$")


def _backup_dir():
    return os.path.join(os.path.dirname(get_database_path()), "backups")


def _verify_backup_file(path):
    """Return an error message when the file is not a usable database."""
    try:
        test = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = test.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        test.close()
    except sqlite3.Error:
        return "The backup file is not a valid database"
    if tables == 0:
        return "The backup file has no tables"
    return None


@app.post("/api/admin/backup/restore")
@admin_required
def restore_backup(user):
    """Replace the live database with one of the saved backup files."""
    data = request.get_json(force=True) or {}
    name = (data.get("filename") or "").strip()
    if not BACKUP_NAME_RE.match(name):
        return jsonify(ok=False, error="Invalid backup name"), 400
    backup_dir = _backup_dir()
    path = os.path.join(backup_dir, name)
    if not os.path.isfile(path):
        return jsonify(ok=False, error="That backup no longer exists"), 404

    error = _verify_backup_file(path)
    if error:
        return jsonify(ok=False, error=error), 400

    # Save the current database first, so nothing is ever lost.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    auto_backup = os.path.join(backup_dir, f"brewskers-before-restore-{stamp}.db")
    source = sqlite3.connect(get_database_path())
    copy = sqlite3.connect(auto_backup)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()

    # Copy the chosen backup over the live database through the SQLite
    # backup API, which is safe even while other connections exist.
    src = sqlite3.connect(path)
    dst = sqlite3.connect(get_database_path())
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    # The backup may come from an older app version, so apply startup
    # migrations right away, then rebuild the in memory indexes.
    migrate_db()
    reset_all()
    record_activity(
        user_id=user["user_id"],
        action="backup_restored",
        description=f"Restored database from backup {name}, previous data saved as {os.path.basename(auto_backup)}",
        entity_type="system",
    )
    return jsonify(ok=True, auto_backup=os.path.basename(auto_backup))


@app.post("/api/admin/backup/delete")
@admin_required
def delete_backup(user):
    """Delete one saved backup file from the backups folder."""
    data = request.get_json(force=True) or {}
    name = (data.get("filename") or "").strip()
    if not BACKUP_NAME_RE.match(name):
        return jsonify(ok=False, error="Invalid backup name"), 400
    path = os.path.join(_backup_dir(), name)
    if not os.path.isfile(path):
        return jsonify(ok=False, error="That backup no longer exists"), 404
    os.remove(path)
    record_activity(
        user_id=user["user_id"],
        action="backup_deleted",
        description=f"Deleted backup {name}",
        entity_type="system",
    )
    return jsonify(ok=True)


@app.get("/api/admin/reset-data/preview")
@admin_required
def preview_reset_data(user):
    """Count the records each maintenance action would touch, right now."""
    db = connect_db()
    cursor = db.cursor()
    try:
        actions = {}
        for key, spec in MAINTENANCE_ACTIONS.items():
            entry = {"count": cursor.execute(spec["count_sql"]).fetchone()[0]}
            if spec["related_sql"]:
                entry["related"] = cursor.execute(spec["related_sql"]).fetchone()[0]
            actions[key] = entry
    except Exception:
        app.logger.exception("Maintenance preview failed")
        return jsonify(ok=False, error="Could not count the records"), 500
    finally:
        db.close()
    return jsonify(ok=True, actions=actions)


@app.post("/api/admin/reset-data")
@admin_required
def api_admin_reset_data(user):
    """Run one maintenance action chosen on the admin data page."""
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip()
    spec = MAINTENANCE_ACTIONS.get(action)
    if spec is None:
        return jsonify(ok=False, error="Unknown reset action"), 400
    # Permanent deletions and bulk resets need the typed confirmation word.
    # Lighter actions such as deactivating products accept the word but do
    # not require it, so older clients that always send it keep working.
    if spec["confirm_word"]:
        confirmation = (data.get("confirmation") or "").strip().upper()
        if confirmation != spec["confirm_word"]:
            return jsonify(ok=False, error=f"Type {spec['confirm_word']} to confirm"), 400
    db = connect_db()
    cursor = db.cursor()
    try:
        # Child rows go first, so foreign keys stay valid while deleting.
        for statement in spec["steps"]:
            cursor.execute(statement)
        # The last statement is the one the dialog counts, so its rowcount
        # is the number reported back to the admin.
        affected = cursor.rowcount
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Admin data reset failed")
        return jsonify(ok=False, error="Could not clear the selected data"), 500
    finally:
        db.close()
    reset_all()
    message = spec["result"].format(n=affected)
    record_activity(user_id=user["user_id"], action="data_cleared", description=message, entity_type="system")
    return jsonify(ok=True, message=message, affected=affected, action=action)
