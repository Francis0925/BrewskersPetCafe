# Brewskers — system activity recording.

from auth import app, connect_db


def record_activity(
    user_id,
    action,
    description,
    entity_type=None,
    entity_id=None,
):
    """Record one system activity event."""
    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO activity_log "
            "(user_id, action, entity_type, entity_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                action,
                entity_type,
                entity_id,
                description,
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Could not record system activity")
    finally:
        db.close()