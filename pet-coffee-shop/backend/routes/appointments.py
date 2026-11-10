# Brewskers appointments and schedule routes
# Booking, upcoming appointments, schedule view and status updates

import datetime

from flask import jsonify, render_template, request

from backend.auth import app
from backend.config import APPOINTMENT_STATUSES
from backend.errors import InvalidRecordError
from backend.helpers import query, run
from backend.models import Appointment, Service
from backend.permissions import require


APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name
                       FROM appointments a
                       JOIN services s ON s.service_id = a.service_id
                       {where}
                      ORDER BY a.appt_date, a.appt_time"""


def bookable_services():
    """Return the services that can be booked, as plain dictionaries.

    Each row becomes a Service object and is asked whether it is available.
    The same is_available() call on a Product means something different,
    which is the polymorphism of the catalog classes.
    """
    return [
        service.to_dict()
        for service in (
            Service.from_row(row)
            for row in query("SELECT * FROM services ORDER BY name")
        )
        if service.is_available()
    ]


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
        services=bookable_services(),
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
        services=bookable_services(),
        today=datetime.date.today(),
    )


@app.post("/api/appointments")
@require("appointments.write")
def add_appointment(user):
    data = request.get_json(force=True) or {}

    # The Appointment object owns the booking rules. validate() returns the
    # normalized fields or raises InvalidRecordError with the reason.
    try:
        clean = Appointment(**data).validate()
    except InvalidRecordError as error:
        return jsonify(ok=False, error=str(error)), 400

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
