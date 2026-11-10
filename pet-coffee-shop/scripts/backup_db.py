# Brewskers database backup and restore
# Creates a dated backup, verifies it, and restores the latest backup
# when the live database file is missing or empty

import argparse
import datetime
import glob
import os
import sqlite3
import sys

from dotenv import load_dotenv


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = PROJECT_ROOT

load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "petcoffeeshop.db"))
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))


def list_backups():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "brewskers-*.db")))
    return files


def latest_backup():
    # Newest first, skip blank backups so a deleted database never restores empty.
    for candidate in reversed(list_backups()):
        if is_valid_database(candidate):
            return candidate
    return None


def is_valid_database(path):
    """Return True when the file exists and contains at least one table."""
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return False

    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        db.close()
        return tables > 0
    except sqlite3.Error:
        return False


def make_backup():
    # Never create a blank database file as a side effect.
    # sqlite3.connect() on a missing path creates an empty file, so check first.
    if not os.path.exists(DB_PATH):
        print(f"Live database not found: {DB_PATH}")
        backup = latest_backup()
        if backup:
            print(f"Restoring latest backup instead: {backup}")
            restore_backup(backup)
        else:
            print("No backup found in", BACKUP_DIR)
            print("Run scripts/setup.py to create a fresh database.")
            sys.exit(1)
        return DB_PATH

    if not is_valid_database(DB_PATH):
        print(f"Live database is empty or invalid: {DB_PATH}")
        backup = latest_backup()
        if backup:
            print(f"Restoring latest backup instead: {backup}")
            restore_backup(backup)
        else:
            print("No backup found in", BACKUP_DIR)
            print("Run scripts/setup.py to create a fresh database.")
            sys.exit(1)
        return DB_PATH

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(BACKUP_DIR, f"brewskers-{stamp}.db")

    # sqlite3 backup API is safe even while the app is running.
    source = sqlite3.connect(DB_PATH)
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()

    try:
        os.chmod(target, 0o600)
    except OSError:
        pass

    print(f"Backup saved: {target}")
    return target


def restore_backup(backup_path=None):
    """Restore a backup file into the live database path."""
    backup_path = backup_path or latest_backup()

    if not backup_path or not os.path.exists(backup_path):
        print("No backup file to restore.")
        sys.exit(1)

    if not is_valid_database(backup_path):
        print(f"Backup is empty or invalid: {backup_path}")
        sys.exit(1)

    verify(backup_path)

    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    # Remove a blank or invalid live file first so sqlite does not append to it.
    if os.path.exists(DB_PATH) and not is_valid_database(DB_PATH):
        os.remove(DB_PATH)

    source = sqlite3.connect(backup_path)
    target = sqlite3.connect(DB_PATH)
    with target:
        source.backup(target)
    target.close()
    source.close()

    print(f"Database restored from {backup_path} to {DB_PATH}")
    return DB_PATH


def prune(keep):
    files = list_backups()
    for old in files[:-keep]:
        os.remove(old)
        print(f"Removed old backup: {os.path.basename(old)}")


def verify(path):
    """Open the backup read-only, run SQLite integrity check, count rows."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        print(f"VERIFY FAILED: {result}")
        sys.exit(1)

    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    print("Backup passes the integrity check. Rows per table:")
    for name in tables:
        count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name}: {count}")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=14)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--restore",
        nargs="?",
        const="latest",
        help="Restore the latest backup, or a specific backup file path",
    )
    args = parser.parse_args()

    if args.restore:
        if args.restore == "latest":
            restore_backup()
        else:
            restore_backup(args.restore)
    else:
        # If the live database is missing or blank, make_backup restores instead.
        latest = make_backup()
        # Only prune and verify the new backup when a backup file was created.
        if latest != DB_PATH:
            prune(max(1, args.keep))
            if args.verify:
                verify(latest)
