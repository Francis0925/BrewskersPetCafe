# Brewskers CSV utilities
# Import and export helpers for products and services

import csv
import io

from flask import Response


def csv_bytes(headers, rows):
    """Return rows as CSV text for use inside a ZIP file."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(header, "") for header in headers])
    return output.getvalue()


def parse_csv_text(content, required_headers):
    """Parse CSV text from a ZIP entry and verify its headers."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty")
    headers = {
        header.strip().lower(): header
        for header in reader.fieldnames
        if header is not None
    }
    missing = [h for h in required_headers if h not in headers]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))
    return reader, headers


def csv_download(filename, headers, rows):
    """Return records as a downloadable CSV file."""
    output = io.StringIO(newline="")

    writer = csv.writer(output)
    writer.writerow(headers)

    for row in rows:
        writer.writerow([row.get(header, "") for header in headers])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def parse_csv_upload(upload, required_headers):
    """Parse an uploaded CSV and verify its headers."""
    if upload is None:
        raise ValueError("Choose a CSV file")

    filename = (upload.filename or "").lower()

    if not filename.endswith(".csv"):
        raise ValueError("Only CSV files are allowed")

    raw = upload.read()

    if not raw:
        raise ValueError("The CSV file is empty")

    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The CSV must use UTF-8 encoding")

    reader = csv.DictReader(io.StringIO(content))

    if not reader.fieldnames:
        raise ValueError("The CSV file is empty")

    headers = {
        header.strip().lower(): header
        for header in reader.fieldnames
        if header is not None
    }

    missing = [header for header in required_headers if header not in headers]

    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))

    return reader, headers


def csv_value(row, headers, key, default=""):
    """Read one normalized field from a CSV row."""
    original_header = headers.get(key)

    if original_header is None:
        return default

    value = row.get(original_header)

    if value is None:
        return default

    return str(value).strip()


def parse_active(value, default=True):
    """Convert a CSV active value into a SQLite integer."""
    value = str(value).strip().lower()

    if value == "":
        return 1 if default else 0

    if value in {"1", "true", "yes", "on", "active"}:
        return 1

    if value in {"0", "false", "no", "off", "inactive"}:
        return 0

    raise ValueError("Active must be 1, 0, true, false, yes, or no")


def validate_product_csv_row(row, headers):
    """Validate and normalize one product CSV row."""
    name = csv_value(row, headers, "name")
    category = csv_value(row, headers, "category")
    price_text = csv_value(row, headers, "price")
    stock_text = csv_value(row, headers, "stock")

    if not name:
        raise ValueError("Name is required")

    if not category:
        raise ValueError("Category is required")

    try:
        price = float(price_text)
    except (TypeError, ValueError):
        raise ValueError("Price must be a valid number")

    try:
        stock = int(stock_text or "0")
    except (TypeError, ValueError):
        raise ValueError("Stock must be a whole number")

    if price < 0:
        raise ValueError("Price cannot be negative")

    if stock < 0:
        raise ValueError("Stock cannot be negative")

    return {"name": name, "category": category, "price": price, "stock": stock}


def validate_service_csv_row(row, headers):
    """Validate and normalize one service CSV row."""
    name = csv_value(row, headers, "name")
    price_text = csv_value(row, headers, "price")
    duration_text = csv_value(row, headers, "duration")
    active_text = csv_value(row, headers, "active", "1")

    if not name:
        raise ValueError("Name is required")

    try:
        price = float(price_text)
    except (TypeError, ValueError):
        raise ValueError("Price must be a valid number")

    try:
        duration = int(duration_text)
    except (TypeError, ValueError):
        raise ValueError("Duration must be a whole number")

    if price < 0:
        raise ValueError("Price cannot be negative")

    if duration <= 0:
        raise ValueError("Duration must be greater than zero")

    try:
        active = parse_active(active_text)
    except ValueError as error:
        raise ValueError(str(error))

    return {"name": name, "price": price, "duration": duration, "active": active}
