# Brewskers appointments and schedule routes
# Booking, upcoming appointments, schedule view and status updates

import datetime

from flask import jsonify, render_template, request

from backend.activity import record_activity
from backend.auth import app, connect_db
from backend.config import (
    APPOINTMENT_CLOSE_TIME,
    APPOINTMENT_OPEN_TIME,
    APPOINTMENT_SLOT_MINUTES,
    APPOINTMENT_STATUSES,
)
from backend.errors import InvalidRecordError
from backend.helpers import (
    _busy_spans_with_connection,
    _find_conflict_with_connection,
    _suggest_next_free_time_with_connection,
    conflict_message,
    query,
)
from backend.models import Appointment, Service
from backend.permissions import require


APPOINTMENT_SQL = """SELECT a.*, s.name AS service_name,
                            s.price AS service_price,
                            s.duration AS service_duration
                       FROM appointments a
                       JOIN services s ON s.service_id = a.service_id
                       {where}
                      ORDER BY a.appt_date, a.appt_time"""


def appointment_slot_context():
    """Slot picker settings shared by the appointment dialog."""
    return {
        "slot_open": APPOINTMENT_OPEN_TIME,
        "slot_close": APPOINTMENT_CLOSE_TIME,
        "slot_minutes": APPOINTMENT_SLOT_MINUTES,
    }


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
        **appointment_slot_context(),
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
        **appointment_slot_context(),
    )


@app.get("/api/appointments/availability")
@require("appointments.read")
def appointment_availability(user):
    """Return the busy spans for one day, used by the live booking check."""
    raw_date = (request.args.get("date") or "").strip()
    try:
        day = datetime.date.fromisoformat(raw_date)
    except ValueError:
        return jsonify(ok=False, error="Choose a valid date"), 400

    service_id = None
    raw_service = (request.args.get("service_id") or "").strip()
    if raw_service:
        try:
            service_id = int(raw_service)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Choose a service"), 400

    exclude_id = None
    raw_exclude = (request.args.get("exclude_id") or "").strip()
    if raw_exclude:
        try:
            exclude_id = int(raw_exclude)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Invalid appointment"), 400

    db = connect_db()
    try:
        spans = _busy_spans_with_connection(
            db, day.isoformat(), exclude_id=exclude_id
        )
        duration = 0
        if service_id is not None:
            row = db.execute(
                "SELECT duration FROM services WHERE service_id = ?",
                (service_id,),
            ).fetchone()
            duration = int(row["duration"] or 0) if row else 0
    finally:
        db.close()

    return jsonify(
        ok=True,
        date=day.isoformat(),
        service_id=service_id,
        duration=duration,
        busy=spans,
    )


def _rollback_quietly(db):
    """Roll back an open transaction without hiding the original error."""
    try:
        db.execute("ROLLBACK")
    except Exception:
        pass


@app.post("/api/appointments")
@require("appointments.write")
def add_appointment(user):
    data = request.get_json(force=True) or {}

    # The Appointment object owns the booking rules. validate() returns the
    # normalized fields or raises InvalidRecordError with the reason. It does
    # not touch the database, so the clash check below stays a separate step.
    try:
        clean = Appointment(**data).validate()
    except InvalidRecordError as error:
        return jsonify(ok=False, error=str(error)), 400

    db = connect_db()
    db.isolation_level = None
    try:
        # One immediate transaction covers the clash check and the insert,
        # so two staff members cannot both take the same slot.
        db.execute("BEGIN IMMEDIATE")

        conflict = _find_conflict_with_connection(
            db,
            clean["appt_date"],
            clean["appt_time"],
            clean["service_id"],
        )

        if conflict:
            suggestion = _suggest_next_free_time_with_connection(
                db,
                clean["appt_date"],
                clean["appt_time"],
                clean["service_id"],
            )
            db.execute("ROLLBACK")
            return (
                jsonify(
                    ok=False,
                    error=conflict_message(conflict, suggestion),
                    conflict=conflict,
                    suggestion=suggestion,
                ),
                409,
            )

        cursor = db.execute(
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
        new_id = cursor.lastrowid
        db.execute("COMMIT")
    except Exception:
        _rollback_quietly(db)
        raise
    finally:
        db.close()

    return jsonify(ok=True, appointment_id=new_id)


@app.post("/api/appointments/<int:appointment_id>/update")
@require("appointments.write")
def update_appointment(user, appointment_id):
    """Edit an existing booking, re-checking the slot against every other row."""
    data = request.get_json(force=True) or {}

    try:
        clean = Appointment(**data).validate()
    except InvalidRecordError as error:
        return jsonify(ok=False, error=str(error)), 400

    db = connect_db()
    db.isolation_level = None
    try:
        db.execute("BEGIN IMMEDIATE")

        exists = db.execute(
            "SELECT appointment_id FROM appointments WHERE appointment_id = ?",
            (appointment_id,),
        ).fetchone()

        if not exists:
            db.execute("ROLLBACK")
            return jsonify(ok=False, error="Appointment not found"), 404

        # The row being edited is excluded so saving without changing the
        # time does not clash with itself.
        conflict = _find_conflict_with_connection(
            db,
            clean["appt_date"],
            clean["appt_time"],
            clean["service_id"],
            exclude_id=appointment_id,
        )

        if conflict:
            suggestion = _suggest_next_free_time_with_connection(
                db,
                clean["appt_date"],
                clean["appt_time"],
                clean["service_id"],
                exclude_id=appointment_id,
            )
            db.execute("ROLLBACK")
            return (
                jsonify(
                    ok=False,
                    error=conflict_message(conflict, suggestion),
                    conflict=conflict,
                    suggestion=suggestion,
                ),
                409,
            )

        db.execute(
            """UPDATE appointments
                  SET pet_name = ?, pet_type = ?, breed = ?, pet_age = ?,
                      owner_name = ?, phone = ?, service_id = ?,
                      appt_date = ?, appt_time = ?, notes = ?, photo = ?
                WHERE appointment_id = ?""",
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
                appointment_id,
            ),
        )
        db.execute("COMMIT")
    except Exception:
        _rollback_quietly(db)
        raise
    finally:
        db.close()

    record_activity(
        user_id=user["user_id"],
        action="appointment_updated",
        description=f"Updated appointment APT-{appointment_id:03d}",
        entity_type="appointment",
        entity_id=appointment_id,
    )

    return jsonify(ok=True, appointment_id=appointment_id)


@app.post("/api/appointments/<int:appointment_id>/status")
@require("appointments.write")
def set_appointment_status(user, appointment_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")

    if status not in APPOINTMENT_STATUSES:
        return jsonify(ok=False, error="Unknown status"), 400

    db = connect_db()
    db.isolation_level = None
    try:
        db.execute("BEGIN IMMEDIATE")

        row = db.execute(
            """SELECT appt_date, appt_time, service_id,
                      COALESCE(status, 'scheduled') AS status
                 FROM appointments
                WHERE appointment_id = ?""",
            (appointment_id,),
        ).fetchone()

        if not row:
            db.execute("ROLLBACK")
            return jsonify(ok=False, error="Appointment not found"), 404

        # A cancelled visit blocks nothing. Bringing one back must pass the
        # same overlap check a brand new booking does, ignoring its own row.
        if row["status"] == "cancelled" and status != "cancelled":
            conflict = _find_conflict_with_connection(
                db,
                row["appt_date"],
                row["appt_time"],
                row["service_id"],
                exclude_id=appointment_id,
            )

            if conflict:
                suggestion = _suggest_next_free_time_with_connection(
                    db,
                    row["appt_date"],
                    row["appt_time"],
                    row["service_id"],
                    exclude_id=appointment_id,
                )
                db.execute("ROLLBACK")
                return (
                    jsonify(
                        ok=False,
                        error=conflict_message(conflict, suggestion),
                        conflict=conflict,
                        suggestion=suggestion,
                    ),
                    409,
                )

        db.execute(
            "UPDATE appointments SET status = ? WHERE appointment_id = ?",
            (status, appointment_id),
        )
        db.execute("COMMIT")
    except Exception:
        _rollback_quietly(db)
        raise
    finally:
        db.close()

    return jsonify(ok=True)
