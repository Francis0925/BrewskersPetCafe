# Brewskers inventory routes
# Product listing, adding products with pictures, stock updates and soft delete

import os
import uuid

from flask import jsonify, render_template, request
from werkzeug.utils import secure_filename

from backend.auth import app
from backend.algorithms import binary_search, merge_sort
from backend.database import PROJECT_ROOT
from backend.helpers import query, run
from backend.permissions import require
from backend.settings import get_store_settings
from backend.pos_state import product_index


IMAGE_DIR = os.path.join(PROJECT_ROOT, "frontend", "static", "product_images")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def save_product_image(upload, product_id):
    """Save an uploaded product picture and return its relative path."""
    if upload is None or not upload.filename:
        return None, None

    filename = secure_filename(upload.filename or "")
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return None, "Picture must be JPG, PNG or WebP"

    os.makedirs(IMAGE_DIR, exist_ok=True)

    stored_name = f"{product_id}_{uuid.uuid4().hex[:8]}_{filename}"
    target = os.path.join(IMAGE_DIR, stored_name)

    upload.save(target)

    if os.path.getsize(target) > MAX_IMAGE_BYTES:
        os.remove(target)
        return None, "Picture must be 2 MB or smaller"

    return f"product_images/{stored_name}", None


@app.get("/inventory")
@require("inventory.read")
def inventory(user):
    products = query(
        "SELECT * FROM products WHERE status != 'hidden' ORDER BY category, name"
    )

    return render_template(
        "inventory.html",
        user=user,
        active="inventory",
        title="Inventory",
        products=products,
        low_stock_limit=get_store_settings().low_stock_limit,
    )


@app.post("/api/products")
@require("inventory.write")
def add_product(user):
    # Accept both JSON (old way) and multipart form with a picture file.
    is_multipart = request.content_type and "multipart/form-data" in request.content_type

    if is_multipart:
        data = request.form
        upload = request.files.get("image")
    else:
        data = request.get_json(force=True) or {}
        upload = None

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()

    try:
        price = float(data.get("price"))
        stock = int(data.get("stock") or 0)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Price and stock must be numbers"), 400

    if not name or not category or price < 0 or stock < 0:
        return jsonify(ok=False, error="Fill in name, category, price and stock"), 400

    # A product name can only exist once, including hidden items, so the
    # manual form stays consistent with the CSV import, which updates an
    # existing name instead of adding a second row. Binary search needs a
    # sorted list, so the names are merge sorted first.
    names = merge_sort([row["name"] for row in query("SELECT name FROM products")])
    if binary_search(names, name) >= 0:
        return jsonify(ok=False, error="A product with this name already exists"), 409

    image_path = None
    if upload is not None and upload.filename:
        # Use a temporary id for the filename, then fix it after insert.
        image_path, error = save_product_image(upload, 0)
        if error:
            return jsonify(ok=False, error=error), 400

    product_id = run(
        "INSERT INTO products (category, name, price, stock, image) VALUES (?, ?, ?, ?, ?)",
        (category, name, price, stock, image_path),
    )

    # Rename the file to include the real product id for tidiness.
    if image_path:
        old_file = os.path.join(IMAGE_DIR, os.path.basename(image_path))
        new_name = f"{product_id}_{os.path.basename(image_path).split('_', 1)[-1]}"
        new_file = os.path.join(IMAGE_DIR, new_name)
        try:
            os.rename(old_file, new_file)
            run("UPDATE products SET image = ? WHERE product_id = ?", (f"product_images/{new_name}", product_id))
        except OSError:
            pass

    product_index.invalidate()
    return jsonify(ok=True, product_id=product_id, image=image_path)


@app.post("/api/products/<int:product_id>/image")
@require("inventory.write")
def update_product_image(user, product_id):
    existing = query("SELECT product_id FROM products WHERE product_id = ?", (product_id,), one=True)
    if not existing:
        return jsonify(ok=False, error="Product not found"), 404

    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return jsonify(ok=False, error="Choose a picture file"), 400

    image_path, error = save_product_image(upload, product_id)
    if error:
        return jsonify(ok=False, error=error), 400

    run("UPDATE products SET image = ? WHERE product_id = ?", (image_path, product_id))
    product_index.invalidate()
    return jsonify(ok=True, image=image_path)


@app.post("/api/products/<int:product_id>/stock")
@require("inventory.write")
def set_stock(user, product_id):
    data = request.get_json(force=True) or {}
    amount = data.get("stock")

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Stock must be a whole number"), 400

    if amount < 0:
        return jsonify(ok=False, error="Stock cannot be negative"), 400

    if data.get("restock"):
        run(
            "UPDATE products SET stock = stock + ? WHERE product_id = ?",
            (amount, product_id),
        )
    else:
        run("UPDATE products SET stock = ? WHERE product_id = ?", (amount, product_id))

    product_index.invalidate()
    return jsonify(ok=True)


@app.delete("/api/products/<int:product_id>")
@require("inventory.write")
def remove_product(user, product_id):
    run("UPDATE products SET status = 'hidden' WHERE product_id = ?", (product_id,))
    product_index.invalidate()
    return jsonify(ok=True)
