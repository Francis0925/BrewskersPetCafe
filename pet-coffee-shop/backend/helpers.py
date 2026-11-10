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
