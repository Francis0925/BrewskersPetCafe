# Brewskers data tools routes
# CSV and SQL import and export for all data, plus admin data reset

import csv
import datetime
import io
import os
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
from backend.database import get_database_path
from backend.helpers import query, run
from backend.permissions import admin_required


EXPORT_ALL_TABLES = {
    "products": ["category", "name", "price", "stock", "status", "image"],
    "services": ["name", "price", "duration", "active"],
    "orders": ["order_no", "customer_name", "total_amount", "payment_method", "amount_paid", "change_amount", "status"],
    "order_items": ["order_no", "product_name", "quantity", "price"],
    "appointments": ["pet_name", "pet_type", "breed", "pet_age", "owner_name", "phone", "service_name", "appt_date", "appt_time", "status", "notes"],
    "store_profile": ["store_name", "address", "phone", "email"],
}


def _export_all_rows():
    products = query("SELECT category, name, price, stock, status, COALESCE(image, '') AS image FROM products ORDER BY category, name")
    services = query("SELECT name, price, duration, active FROM services ORDER BY name")
    orders = query(
        "SELECT order_no, COALESCE(customer_name, '') AS customer_name, total_amount, payment_method, "
        "COALESCE(amount_paid, '') AS amount_paid, COALESCE(change_amount, '') AS change_amount, "
        "COALESCE(status, 'completed') AS status FROM orders ORDER BY order_date, order_id"
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
    store_profile = query("SELECT store_name, COALESCE(address, '') AS address, COALESCE(phone, '') AS phone, COALESCE(email, '') AS email FROM store_profile")
    return {
        "products": products,
        "services": services,
        "orders": orders,
        "order_items": order_items,
        "appointments": appointments,
        "store_profile": store_profile,
    }


@app.get("/admin/data")
@admin_required
def admin_data(user):
    return render_template(
        "data_tools.html",
        title="Import & export",
        active="admin",
        user=user,
        exports={"products": "Products", "services": "Services", "orders": "Orders", "appointments": "Appointments"},
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
                cursor.execute(
                    "INSERT INTO orders (order_no, customer_name, total_amount, payment_method, amount_paid, change_amount, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (order_no, (row.get("customer_name") or "Walk-in").strip() or "Walk-in", total, (row.get("payment_method") or "cash").strip() or "cash", row.get("amount_paid") or None, row.get("change_amount") or None, status),
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
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Import all failed")
        return jsonify(ok=False, error="Could not import the ZIP file"), 500
    finally:
        db.close()
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
    profile = query("SELECT * FROM store_profile LIMIT 1", one=True) or {"store_name": "Brewskers", "address": "", "phone": "", "email": ""}
    db_path = get_database_path()
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    backups = sorted([f for f in os.listdir(backup_dir) if f.endswith(".db")]) if os.path.exists(backup_dir) else []
    return render_template("settings.html", user=user, active="admin", title="Settings", profile=profile, db_size=db_size, backups=backups)


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
    record_activity(user_id=user["user_id"], action="settings_updated", description="Updated store settings", entity_type="system")
    return jsonify(ok=True)


@app.post("/api/admin/reset-data")
@admin_required
def api_admin_reset_data(user):
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip()
    confirmation = (data.get("confirmation") or "").strip().upper()
    if confirmation != "DELETE":
        return jsonify(ok=False, error="Type DELETE to confirm"), 400
    descriptions = {
        "reset_stock": "Reset all product stock to zero",
        "hide_products": "Hid all products from inventory and the POS",
        "hide_services": "Hid all services from booking",
        "delete_appointments": "Deleted all appointments",
        "delete_orders": "Deleted all order and receipt history",
        "delete_activity": "Cleared all recent activity",
    }
    if action not in descriptions:
        return jsonify(ok=False, error="Unknown reset action"), 400
    db = connect_db()
    cursor = db.cursor()
    try:
        if action == "reset_stock":
            cursor.execute("UPDATE products SET stock = 0")
        elif action == "hide_products":
            cursor.execute("UPDATE products SET status = 'hidden'")
        elif action == "hide_services":
            cursor.execute("UPDATE services SET active = 0")
        elif action == "delete_appointments":
            cursor.execute("DELETE FROM appointments")
        elif action == "delete_orders":
            cursor.execute("DELETE FROM order_items")
            cursor.execute("DELETE FROM orders")
        elif action == "delete_activity":
            cursor.execute("DELETE FROM activity_log")
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Admin data reset failed")
        return jsonify(ok=False, error="Could not clear the selected data"), 500
    finally:
        db.close()
    record_activity(user_id=user["user_id"], action="data_cleared", description=descriptions[action], entity_type="system")
    return jsonify(ok=True, message=descriptions[action])
