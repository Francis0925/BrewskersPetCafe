"""Tests for the order search endpoint.

Run from the project root with:
    py -m unittest tests.test_order_search

The tests point DATABASE_PATH at a temporary file before backend modules are
imported, so the live database is never touched.
"""

import hashlib
import hmac
import os
import re
import tempfile
import unittest
from urllib.parse import urlencode

TEMP_DIR = tempfile.mkdtemp(prefix="brewskers-order-search-tests-")
os.environ["DATABASE_PATH"] = os.path.join(TEMP_DIR, "test.db")
os.environ["BACKUP_DIR"] = os.path.join(TEMP_DIR, "backups")
os.environ["SECRET_KEY"] = "order-search-tests-secret"

from backend.auth import app, connect_db  # noqa: E402
import backend.routes  # noqa: E402,F401


def csrf_header(session_token):
    digest = hmac.new(
        str(app.config["SECRET_KEY"]).encode(),
        session_token.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {"X-CSRF-Token": digest}


def visible_text(html):
    """Strip tags so assertions can look at what the user actually sees."""
    return re.sub(r"<[^>]+>", "", html)


class OrderSearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_db()
        self.addCleanup(self.conn.close)

        self.conn.execute("DELETE FROM orders")
        self.conn.execute("DELETE FROM sessions")
        self.conn.commit()

        self.admin_id = self.conn.execute(
            "SELECT user_id FROM users WHERE username = 'admin'"
        ).fetchone()["user_id"]

        self.session_token = "order-search-tests-token"
        self.conn.execute(
            "INSERT INTO sessions (user_id, token, expires_at) "
            "VALUES (?, ?, datetime('now', '+1 day', 'localtime'))",
            (self.admin_id, self.session_token),
        )
        self.conn.commit()

        self.client = app.test_client()
        self.client.set_cookie("session", self.session_token)
        self.headers = csrf_header(self.session_token)

    def order(
        self,
        order_no,
        customer="Walk-in",
        payment="cash",
        status="completed",
        date="2026-01-01 10:00:00",
        created_by=None,
    ):
        self.conn.execute(
            """INSERT INTO orders
                 (order_no, customer_name, total_amount, payment_method,
                  status, order_date, created_by, tax_rate)
               VALUES (?, ?, 100.0, ?, ?, ?, ?, 12.0)""",
            (order_no, customer, payment, status, date, created_by),
        )
        self.conn.commit()

    def search(self, **params):
        query = urlencode(params)
        response = self.client.get(f"/orders/search?{query}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    # Matching rules

    def test_customer_name_starts_a_word(self):
        self.order("H1001", customer="Maria Santos")
        self.order("H1002", customer="Tamara Cruz")

        body = self.search(page="history", status="all", q="mar")

        self.assertEqual(body["total"], 1)
        self.assertIn("Santos", visible_text(body["html"]))
        self.assertNotIn("Tamara", visible_text(body["html"]))

    def test_cashier_name_starts_a_word(self):
        other = self.conn.execute(
            "INSERT INTO users (username, email, password, role) "
            "VALUES ('carlos', 'carlos@test.local', 'x', 'staff')"
        ).lastrowid
        self.conn.commit()

        self.order("H1001", customer="Ana", created_by=other)
        self.order("H1002", customer="Ben")

        body = self.search(page="history", status="all", q="carl")

        self.assertEqual(body["total"], 1)
        self.assertIn("Ana", body["html"])
        self.assertNotIn("Ben", body["html"])

    def test_order_number_prefix_ignores_hash(self):
        self.order("H1042")
        self.order("H2042")

        body = self.search(page="history", status="all", q="#H104")

        self.assertEqual(body["total"], 1)
        self.assertIn("H1042", body["html"])

    def test_three_digit_token_matches_inside_order_number(self):
        self.order("2026-1042")
        self.order("2026-9999")

        body = self.search(page="history", status="all", q="104")

        self.assertEqual(body["total"], 1)
        self.assertIn("2026-1042", visible_text(body["html"]))

    def test_two_digit_token_does_not_match_inside_order_number(self):
        self.order("2026-1042")

        body = self.search(page="history", status="all", q="10")

        self.assertEqual(body["total"], 0)

    def test_payment_method_prefix(self):
        self.order("H1001", payment="GCash")
        self.order("H1002", payment="cash")

        body = self.search(page="history", status="all", q="gc")

        self.assertEqual(body["total"], 1)
        self.assertIn("GCASH", visible_text(body["html"]))

    def test_tokens_are_combined_with_and(self):
        self.order("H1001", customer="Maria", payment="cash")
        self.order("H1002", customer="Maria", payment="GCash")
        self.order("H1003", customer="Ben", payment="cash")

        body = self.search(page="history", status="all", q="mar cash")

        self.assertEqual(body["total"], 1)
        self.assertIn("H1001", body["html"])

    def test_like_wildcards_are_escaped(self):
        self.order("H2001", customer="100% pure")
        self.order("H2002", customer="Plain")

        percent = self.search(page="history", status="all", q="100%")
        underscore = self.search(page="history", status="all", q="_")

        self.assertEqual(percent["total"], 1)
        self.assertEqual(underscore["total"], 0)

    def test_blank_query_returns_the_whole_scope(self):
        self.order("H1001", status="completed")
        self.order("H1002", status="cancelled")
        self.order("H1003", status="queued")

        body = self.search(page="history", status="all", q="")
        completed = self.search(page="history", status="completed", q="")
        queued = self.search(page="queued", q="")

        self.assertEqual(body["total"], 2)
        self.assertEqual(completed["total"], 1)
        self.assertEqual(queued["total"], 1)
        self.assertNotIn("H1003", body["html"])

    def test_history_never_returns_queued_orders(self):
        self.order("H1001", status="queued")

        body = self.search(page="history", status="all", q="")

        self.assertEqual(body["total"], 0)
        self.assertIn("No orders in history", body["html"])

    def test_newest_order_comes_first(self):
        self.order("H1001", date="2026-01-01 10:00:00")
        self.order("H1002", date="2026-01-05 10:00:00")

        body = self.search(page="history", status="all", q="")

        self.assertLess(body["html"].index("H1002"), body["html"].index("H1001"))

    def test_counts_cover_the_whole_table(self):
        self.order("H1001", customer="Maria", status="completed")
        self.order("H1002", customer="Ben", status="completed")
        self.order("H1003", customer="Ben", status="cancelled")
        self.order("H1004", customer="Ben", status="queued")

        body = self.search(page="history", status="all", q="mar")

        self.assertEqual(body["total"], 1)
        self.assertEqual(body["counts"]["completed"], 2)
        self.assertEqual(body["counts"]["cancelled"], 1)
        self.assertEqual(body["counts"]["queued"], 1)

    def test_pagination_reports_shown_and_has_more(self):
        for index in range(30):
            self.order(f"H{2000 + index}", date=f"2026-02-01 10:{index:02d}:00")

        first = self.search(page="history", status="all", q="", limit=25)
        second = self.search(
            page="history", status="all", q="", limit=25, offset=25
        )

        self.assertEqual(first["total"], 30)
        self.assertEqual(first["shown"], 25)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["shown"], 30)
        self.assertFalse(second["has_more"])

    def test_matches_are_highlighted(self):
        self.order("H1001", customer="Maria Santos")

        body = self.search(page="history", status="all", q="mar")

        self.assertIn("<mark>Mar</mark>ia", body["html"])

    def test_html_is_escaped(self):
        self.order("H1001", customer="<script>alert(1)</script>")

        body = self.search(page="history", status="all", q="<script>")

        self.assertEqual(body["total"], 1)
        self.assertIn("&lt;script&gt;", body["html"])
        self.assertNotIn("<script>alert(1)</script>", body["html"])

    def test_no_results_mentions_the_query(self):
        body = self.search(page="history", status="all", q="no-such-order")

        self.assertEqual(body["total"], 0)
        self.assertIn("No orders match", body["html"])
        self.assertIn("no-such-order", body["html"])

    def test_unknown_status_falls_back_to_all_history(self):
        self.order("H1001", status="completed")
        self.order("H1002", status="cancelled")

        body = self.search(page="history", status="nonsense", q="")

        self.assertEqual(body["total"], 2)

    def test_limit_is_capped(self):
        for index in range(3):
            self.order(f"H{3000 + index}")

        body = self.search(page="history", status="all", q="", limit=9999)

        self.assertEqual(body["shown"], 3)

    def test_search_requires_login(self):
        anonymous = app.test_client()
        response = anonymous.get("/orders/search?page=history")

        # Page style URLs redirect to login; API style URLs answer 401.
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
