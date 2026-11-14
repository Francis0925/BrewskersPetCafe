# Brewskers system activity recording
# Records admin and system actions in the activity log

import logging

from backend.database import connect_db


logger = logging.getLogger("backend.auth")


def record_activity(user_id, action, description, entity_type=None, entity_id=None):
    """Record one system activity event."""
    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO activity_log "
            "(user_id, action, entity_type, entity_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, action, entity_type, entity_id, description),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record system activity")
    finally:
        db.close()
