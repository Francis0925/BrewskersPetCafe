# Brewskers appointments and schedule routes
# Booking, upcoming appointments, schedule view and status updates

import datetime

from flask import jsonify, render_template, request

from backend.auth import app
from backend.config import APPOINTMENT_STATUSES
from backend.helpers import query, run
from backend.permissions import require
from backend.security import validate_appointment


APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name
                       FROM appointments a
                       JOIN services s ON s.service_id = a.service_id
                       {where}
                      ORDER BY a.appt_date, a.appt_time"""


@app.get("/appointments")
@require("appointments.read")
def appointments(user):
    upcoming = query(
        APPOINTMENT_SQL.format(
            where="WHERE a.appt_date >= date('now', 'localtime') AND a.status = 'scheduled'"
        )
    )

    return render_template(
        "appointments.html",
        user=user,
        active="appointments",
        title="Appointments",
        appointments=upcoming,
        services=query("SELECT * FROM services WHERE active = 1 ORDER BY name"),
        today=datetime.date.today(),
    )


@app.get("/schedule")
@require("appointments.read")
def schedule(user):
    appointments_list = query(
        APPOINTMENT_SQL.format(where="WHERE a.status != 'cancelled'")
    )

    return render_template(
        "schedule.html",
        user=user,
        active="schedule",
        title="Schedule",
        appointments=appointments_list,
        services=query("SELECT * FROM services WHERE active = 1 ORDER BY name"),
        today=datetime.date.today(),
    )


@app.post("/api/appointments")
@require("appointments.write")
def add_appointment(user):
    data = request.get_json(force=True) or {}

    # Use the shared validator so phone, date, photo and text rules are enforced
    clean, error = validate_appointment(data)

    if error:
        return jsonify(ok=False, error=error), 400

    run(
        """INSERT INTO appointments
             (pet_name, pet_type, breed, pet_age, owner_name, phone,
              service_id, appt_date, appt_time, notes, photo, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            clean["pet_name"],
            clean["pet_type"],
            clean["breed"],
            clean["pet_age"],
            clean["owner_name"],
            clean["phone"],
            clean["service_id"],
            clean["appt_date"],
            clean["appt_time"],
            clean["notes"],
            clean["photo"],
            user["user_id"],
        ),
    )

    return jsonify(ok=True)


@app.post("/api/appointments/<int:appointment_id>/status")
@require("appointments.write")
def set_appointment_status(user, appointment_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")

    if status not in APPOINTMENT_STATUSES:
        return jsonify(ok=False, error="Unknown status"), 400

    run(
        "UPDATE appointments SET status = ? WHERE appointment_id = ?",
        (status, appointment_id),
    )

    return jsonify(ok=True)
