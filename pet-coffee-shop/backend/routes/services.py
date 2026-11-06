# Brewskers services routes
# Pet service listing, adding and updating services

from flask import jsonify, render_template, request

from backend.auth import app
from backend.helpers import query, run
from backend.permissions import admin_required, require


@app.get("/services")
@require("services.read")
def services_page(user):
    services = query("SELECT * FROM services ORDER BY name")

    return render_template(
        "services.html",
        user=user,
        active="services",
        title="Services",
        services=services,
    )


@app.post("/api/services")
@admin_required
def add_service(user):
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()

    try:
        price = float(data.get("price"))
        duration = int(data.get("duration") or 30)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Price and duration must be numbers"), 400

    if not name or price < 0 or duration <= 0:
        return jsonify(ok=False, error="Fill in name, price and duration"), 400

    run("INSERT INTO services (name, price, duration) VALUES (?, ?, ?)", (name, price, duration))

    return jsonify(ok=True)


@app.post("/api/services/<int:service_id>")
@admin_required
def update_service(user, service_id):
    data = request.get_json(force=True) or {}
    fields = []
    values = []

    for key in ("name", "price", "duration", "active"):
        if key not in data:
            continue

        if key == "name":
            value = (data.get("name") or "").strip()

            if not value:
                return jsonify(ok=False, error="Service name is required"), 400
        elif key == "price":
            try:
                value = float(data.get("price"))
            except (TypeError, ValueError):
                return jsonify(ok=False, error="Price must be a number"), 400

            if value < 0:
                return jsonify(ok=False, error="Price cannot be negative"), 400
        elif key == "duration":
            try:
                value = int(data.get("duration"))
            except (TypeError, ValueError):
                return jsonify(ok=False, error="Duration must be a number"), 400

            if value <= 0:
                return jsonify(ok=False, error="Duration must be greater than zero"), 400
        else:
            value = 1 if bool(data.get("active")) else 0

        fields.append(f"{key} = ?")
        values.append(value)

    if not fields:
        return jsonify(ok=False, error="No fields to update"), 400

    values.append(service_id)

    run(f"UPDATE services SET {', '.join(fields)} WHERE service_id = ?", tuple(values))

    return jsonify(ok=True)
