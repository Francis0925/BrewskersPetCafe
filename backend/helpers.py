# Brewskers database helpers
# Small wrappers for running queries and cleaning rows for display

import datetime
import decimal

from backend.database import connect_db


def clean(row):
    """Convert database values into JSON-friendly Python values."""
    result = dict(row)

    for key, value in list(result.items()):
        if isinstance(value, decimal.Decimal):
            result[key] = float(value)
        elif isinstance(value, datetime.timedelta):
            result[key] = str(value)[:-3].zfill(5)
        elif isinstance(value, datetime.date):
            result[key] = value.isoformat()

    return result


def query(sql, args=(), one=False, default=None):
    """Run a SELECT query and return all rows or one row."""
    db = connect_db()
    rows = [clean(row) for row in db.execute(sql, args).fetchall()]
    db.close()

    if one:
        return rows[0] if rows else default

    return rows


def run(sql, args=()):
    """Run an INSERT, UPDATE, or DELETE query and commit it."""
    db = connect_db()
    cursor = db.cursor()
    cursor.execute(sql, args)
    new_id = cursor.lastrowid
    db.commit()
    db.close()
    return new_id


# Appointment conflict detection
#
# A visit blocks the room for its whole service duration, not just its start
# time. Two visits overlap when the new one starts before the existing one
# ends and the existing one starts before the new one ends. Back-to-back
# bookings (one ends exactly when the next starts) are allowed.
#
# For one day there are k live appointments. The day scan is O(k) because
# idx_appointments_date finds the day's rows directly, and the overlap test
# looks at each row once. The next free time walk visits each clashing
# appointment at most once, so it is also O(k), or O(k log k) when the day
# spans are sorted first. Nothing here scans the whole table.

def time_to_minutes(value):
    """Return minutes after midnight for a stored HH:MM value, or None."""
    try:
        hour, minute = str(value or "").split(":")[:2]
        hour = int(hour)
        minute = int(minute)
    except (TypeError, ValueError):
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def minutes_to_time(minutes):
    """Format minutes after midnight as the HH:MM value stored in the database."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_time_12h(value):
    """Turn a stored HH:MM time into a friendly 12-hour label."""
    total = time_to_minutes(value)
    if total is None:
        return str(value or "")

    hour, minute = divmod(total, 60)
    suffix = "AM" if hour < 12 else "PM"
    hour = hour % 12 or 12
    return f"{hour}:{minute:02d} {suffix}"


def _service_length(connection, service_id):
    """Return the service duration in minutes, or 0 when it is unknown."""
    try:
        row = connection.execute(
            "SELECT duration FROM services WHERE service_id = ?",
            (service_id,),
        ).fetchone()
    except Exception:
        return 0

    try:
        return max(0, int(row["duration"] or 0)) if row else 0
    except (TypeError, ValueError, IndexError, KeyError):
        return 0


def _blocking_rows(connection, appt_date, exclude_id=None):
    """Return the live appointments booked on one day.

    Cancelled appointments never block a slot, so they are filtered out in
    SQL. exclude_id drops the appointment being edited, which lets an edit
    keep its own time.
    """
    return connection.execute(
        """SELECT a.appointment_id, a.pet_name, a.appt_time,
                  s.name AS service_name, s.duration
             FROM appointments a
             JOIN services s ON s.service_id = a.service_id
            WHERE a.appt_date = ?
              AND COALESCE(a.status, 'scheduled') != 'cancelled'
              AND (? IS NULL OR a.appointment_id != ?)
            ORDER BY a.appt_time, a.appointment_id""",
        (appt_date, exclude_id, exclude_id),
    ).fetchall()


def _busy_spans_with_connection(connection, appt_date, exclude_id=None):
    """Return the day's busy spans as plain dictionaries, in time order."""
    spans = []

    for row in _blocking_rows(connection, appt_date, exclude_id):
        start = time_to_minutes(row["appt_time"])
        if start is None:
            continue

        try:
            length = max(0, int(row["duration"] or 0))
        except (TypeError, ValueError):
            length = 0

        spans.append(
            {
                "appointment_id": row["appointment_id"],
                "pet_name": row["pet_name"] or "",
                "service_name": row["service_name"] or "",
                "start": minutes_to_time(start),
                "end": minutes_to_time(start + length),
            }
        )

    return spans


def _find_conflict_with_connection(
    connection, appt_date, appt_time, service_id, exclude_id=None
):
    """Return the first clashing appointment on that day, or None."""
    start = time_to_minutes(appt_time)
    if start is None:
        return None

    length = _service_length(connection, service_id)
    if length <= 0:
        return None

    end = start + length

    for row in _blocking_rows(connection, appt_date, exclude_id):
        row_start = time_to_minutes(row["appt_time"])
        if row_start is None:
            continue

        try:
            row_length = max(0, int(row["duration"] or 0))
        except (TypeError, ValueError):
            row_length = 0

        row_end = row_start + row_length

        if start < row_end and row_start < end:
            return {
                "appointment_id": row["appointment_id"],
                "pet_name": row["pet_name"] or "",
                "service_name": row["service_name"] or "",
                "start": minutes_to_time(row_start),
                "end": minutes_to_time(row_end),
            }

    return None


def find_conflict(appt_date, appt_time, service_id, exclude_id=None):
    """Return the live appointment that clashes with a new booking, or None.

    appt_date is YYYY-MM-DD, appt_time is HH:MM and service_id picks the
    appointment length. Cancelled appointments never block a slot. Passing
    exclude_id skips that appointment, so a booking can keep its own time.
    """
    db = connect_db()
    try:
        return _find_conflict_with_connection(
            db, appt_date, appt_time, service_id, exclude_id
        )
    finally:
        db.close()


def _suggest_next_free_time_with_connection(
    connection, appt_date, appt_time, service_id, exclude_id=None
):
    """Return the next free HH:MM for that day, or None when the day is full."""
    start = time_to_minutes(appt_time)
    if start is None:
        return None

    length = _service_length(connection, service_id)
    if length <= 0:
        return None

    spans = _busy_spans_with_connection(connection, appt_date, exclude_id)
    busy = [
        (time_to_minutes(span["start"]), time_to_minutes(span["end"]))
        for span in spans
    ]

    candidate = start

    # Each clash moves the candidate to the end of the clashing visit, so
    # this loop visits every appointment at most once.
    for _ in range(len(busy) + 1):
        if candidate + length > 24 * 60:
            return None

        clash = next(
            (
                (span_start, span_end)
                for span_start, span_end in busy
                if candidate < span_end and span_start < candidate + length
            ),
            None,
        )

        if clash is None:
            return minutes_to_time(candidate)

        candidate = max(candidate, clash[1])

    return None


def suggest_next_free_time(
    appt_date, appt_time, service_id, exclude_id=None
):
    """Return the next free HH:MM on the same day, or None."""
    db = connect_db()
    try:
        return _suggest_next_free_time_with_connection(
            db, appt_date, appt_time, service_id, exclude_id
        )
    finally:
        db.close()


def conflict_message(conflict, suggestion):
    """Build the sentence shown when a booking clashes with another visit."""
    pet = conflict.get("pet_name") or "Another pet"
    service = conflict.get("service_name") or "visit"
    clash = (
        f"{pet}'s {service} is booked from "
        f"{format_time_12h(conflict.get('start'))} to "
        f"{format_time_12h(conflict.get('end'))}"
    )

    if suggestion:
        return f"{clash}. The next free time is {format_time_12h(suggestion)}."

    return f"{clash}. There is no free time left that day."
