"""Tests for the appointment conflict rule.

Run from the project root with:
    py -m unittest tests.test_appointment_conflicts

The tests point DATABASE_PATH at a temporary file before backend modules are
imported, so the live database is never touched.
"""

import datetime
import hashlib
import hmac
import os
import tempfile
import unittest

TEMP_DIR = tempfile.mkdtemp(prefix="brewskers-appointment-tests-")
os.environ["DATABASE_PATH"] = os.path.join(TEMP_DIR, "test.db")
os.environ["BACKUP_DIR"] = os.path.join(TEMP_DIR, "backups")
os.environ["SECRET_KEY"] = "appointment-tests-secret"

from backend.auth import app, connect_db  # noqa: E402
import backend.routes  # noqa: E402,F401

from backend.helpers import (  # noqa: E402
    conflict_message,
    find_conflict,
    format_time_12h,
    suggest_next_free_time,
)


FUTURE = (datetime.date.today() + datetime.timedelta(days=40)).isoformat()


def csrf_header(session_token):
    digest = hmac.new(
        str(app.config["SECRET_KEY"]).encode(),
        session_token.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {"X-CSRF-Token": digest}


class AppointmentConflictTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_db()
        self.addCleanup(self.conn.close)

        self.conn.execute("DELETE FROM appointments")
        self.conn.execute("DELETE FROM services")
        self.conn.execute("DELETE FROM sessions")
        self.conn.commit()

        self.conn.execute(
            "INSERT INTO services (name, price, duration, active) VALUES (?, ?, ?, 1)",
            ("Full grooming", 500.0, 60),
        )
        self.groom = self.conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        self.conn.execute(
            "INSERT INTO services (name, price, duration, active) VALUES (?, ?, ?, 1)",
            ("Nail trim", 150.0, 30),
        )
        self.nails = self.conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        self.conn.commit()

        self.admin_id = self.conn.execute(
            "SELECT user_id FROM users WHERE username = 'admin'"
        ).fetchone()["user_id"]

        self.session_token = "appointment-tests-token"
        self.conn.execute(
            "INSERT INTO sessions (user_id, token, expires_at) "
            "VALUES (?, ?, datetime('now', '+1 day', 'localtime'))",
            (self.admin_id, self.session_token),
        )
        self.conn.commit()

        self.client = app.test_client()
        self.client.set_cookie("session", self.session_token)
        self.headers = csrf_header(self.session_token)

    def seed(self, pet, start, service_id=None, status="scheduled", day=FUTURE):
        self.conn.execute(
            """INSERT INTO appointments
                 (pet_name, pet_type, owner_name, phone, service_id,
                  appt_date, appt_time, status)
               VALUES (?, 'Dog', 'Owner', '09171234567', ?, ?, ?, ?)""",
            (pet, service_id or self.groom, day, start, status),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT last_insert_rowid() AS id"
        ).fetchone()["id"]

    def post_booking(self, start, service_id=None, pet="New pet", day=FUTURE):
        return self.client.post(
            "/api/appointments",
            json={
                "pet_name": pet,
                "pet_type": "Dog",
                "owner_name": "Owner",
                "phone": "09171234567",
                "service_id": service_id or self.groom,
                "appt_date": day,
                "appt_time": start,
            },
            headers=self.headers,
        )

    # Pure conflict rule

    def test_overlapping_visit_is_a_conflict(self):
        self.seed("Buddy", "10:00")

        conflict = find_conflict(FUTURE, "10:30", self.nails)

        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["pet_name"], "Buddy")
        self.assertEqual(conflict["start"], "10:00")
        self.assertEqual(conflict["end"], "11:00")

    def test_back_to_back_visit_is_allowed(self):
        self.seed("Buddy", "10:00")

        self.assertIsNone(find_conflict(FUTURE, "11:00", self.nails))

    def test_cancelled_visit_never_blocks(self):
        self.seed("Buddy", "10:00", status="cancelled")

        self.assertIsNone(find_conflict(FUTURE, "10:15", self.nails))

    def test_exclude_id_skips_the_booking_being_edited(self):
        appointment_id = self.seed("Buddy", "10:00")

        self.assertIsNone(
            find_conflict(FUTURE, "10:00", self.groom, exclude_id=appointment_id)
        )

    def test_overlap_on_another_day_is_ignored(self):
        self.seed("Buddy", "10:00")
        other_day = (
            datetime.date.today() + datetime.timedelta(days=41)
        ).isoformat()

        self.assertIsNone(find_conflict(other_day, "10:00", self.groom))

    # Next free time

    def test_suggestion_moves_to_the_end_of_the_clash(self):
        self.seed("Buddy", "10:00")

        self.assertEqual(
            suggest_next_free_time(FUTURE, "10:30", self.nails), "11:00"
        )

    def test_suggestion_skips_two_back_to_back_clashes(self):
        self.seed("Buddy", "10:00")
        self.seed("Milo", "11:00")

        self.assertEqual(
            suggest_next_free_time(FUTURE, "10:30", self.nails), "12:00"
        )

    def test_twelve_hour_display(self):
        self.assertEqual(format_time_12h("09:05"), "9:05 AM")
        self.assertEqual(format_time_12h("12:00"), "12:00 PM")
        self.assertEqual(format_time_12h("00:30"), "12:30 AM")
        self.assertEqual(format_time_12h("23:45"), "11:45 PM")

    def test_conflict_message_names_the_clash_and_suggestion(self):
        message = conflict_message(
            {
                "pet_name": "Buddy",
                "service_name": "Full grooming",
                "start": "10:00",
                "end": "11:00",
            },
            "11:00",
        )

        self.assertIn("Buddy's Full grooming", message)
        self.assertIn("10:00 AM to 11:00 AM", message)
        self.assertIn("next free time is 11:00 AM", message)

    # HTTP endpoints

    def test_booking_endpoint_returns_409_with_conflict_payload(self):
        self.seed("Buddy", "10:00")

        response = self.post_booking("10:30", self.nails)

        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["conflict"]["pet_name"], "Buddy")
        self.assertEqual(body["conflict"]["service_name"], "Full grooming")
        self.assertEqual(body["suggestion"], "11:00")
        self.assertIn("next free time", body["error"])

        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM appointments"
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_booking_endpoint_inserts_when_free(self):
        response = self.post_booking("14:00", self.nails)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["appointment_id"])

    def test_cancelled_slot_can_be_booked_again(self):
        first = self.post_booking("10:00", self.groom)
        self.assertEqual(first.status_code, 200)

        cancel = self.client.post(
            f"/api/appointments/{first.get_json()['appointment_id']}/status",
            json={"status": "cancelled"},
            headers=self.headers,
        )
        self.assertEqual(cancel.status_code, 200)

        second = self.post_booking("10:00", self.groom)
        self.assertEqual(second.status_code, 200)

    def test_un_cancelling_rechecks_for_a_clash(self):
        first = self.post_booking("10:00", self.groom)
        first_id = first.get_json()["appointment_id"]

        self.client.post(
            f"/api/appointments/{first_id}/status",
            json={"status": "cancelled"},
            headers=self.headers,
        )

        replacement = self.post_booking("10:00", self.groom)
        self.assertEqual(replacement.status_code, 200)

        restore = self.client.post(
            f"/api/appointments/{first_id}/status",
            json={"status": "scheduled"},
            headers=self.headers,
        )

        self.assertEqual(restore.status_code, 409)
        self.assertEqual(
            restore.get_json()["conflict"]["appointment_id"],
            replacement.get_json()["appointment_id"],
        )

    def test_availability_lists_live_spans_only(self):
        self.seed("Buddy", "10:00")
        self.seed("Hidden", "13:00", status="cancelled")

        response = self.client.get(
            f"/api/appointments/availability?date={FUTURE}&service_id={self.nails}"
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["duration"], 30)
        self.assertEqual(len(body["busy"]), 1)
        self.assertEqual(body["busy"][0]["pet_name"], "Buddy")
        self.assertEqual(body["busy"][0]["start"], "10:00")
        self.assertEqual(body["busy"][0]["end"], "11:00")

    def test_availability_rejects_an_invalid_date(self):
        response = self.client.get("/api/appointments/availability?date=not-a-date")

        self.assertEqual(response.status_code, 400)

    # Edit endpoint

    def put_booking(self, appointment_id, start, service_id=None, day=FUTURE, **overrides):
        payload = {
            "pet_name": "Edited pet",
            "pet_type": "Dog",
            "owner_name": "Owner",
            "phone": "09171234567",
            "service_id": service_id or self.groom,
            "appt_date": day,
            "appt_time": start,
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/appointments/{appointment_id}/update",
            json=payload,
            headers=self.headers,
        )

    def test_update_endpoint_saves_changes(self):
        appointment_id = self.seed("Buddy", "10:00")

        response = self.put_booking(
            appointment_id,
            "14:00",
            notes="Grooming notes",
            pet_name="Buddy Two",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

        row = self.conn.execute(
            """SELECT pet_name, appt_time, notes
                 FROM appointments WHERE appointment_id = ?""",
            (appointment_id,),
        ).fetchone()

        self.assertEqual(row["pet_name"], "Buddy Two")
        self.assertEqual(row["appt_time"], "14:00")
        self.assertEqual(row["notes"], "Grooming notes")

    def test_update_endpoint_returns_409_for_another_booking(self):
        first = self.seed("Buddy", "10:00")
        self.seed("Rival", "11:00", service_id=self.nails)

        response = self.put_booking(first, "11:00", service_id=self.nails)

        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["conflict"]["pet_name"], "Rival")
        self.assertTrue(body["suggestion"])

        unchanged = self.conn.execute(
            "SELECT appt_time FROM appointments WHERE appointment_id = ?",
            (first,),
        ).fetchone()
        self.assertEqual(unchanged["appt_time"], "10:00")

    def test_update_endpoint_does_not_conflict_with_itself(self):
        appointment_id = self.seed("Buddy", "10:00")

        response = self.put_booking(appointment_id, "10:00", notes="Same slot")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_update_endpoint_unknown_appointment_is_404(self):
        response = self.put_booking(99999, "10:00")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["ok"])

    def test_update_endpoint_rejects_invalid_input(self):
        appointment_id = self.seed("Buddy", "10:00")

        response = self.put_booking(appointment_id, "10:00", phone="not-a-phone")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_booking_requires_login(self):
        anonymous = app.test_client()
        response = anonymous.post(
            "/api/appointments",
            json={"pet_name": "No session"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
