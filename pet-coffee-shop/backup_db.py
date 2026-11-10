import argparse
import datetime
import glob
import os
import sqlite3
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "petcoffeeshop.db"))
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))


def make_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(BACKUP_DIR, f"brewskers-{stamp}.db")

    # sqlite3's backup API is safe even while the app is running.
    source = sqlite3.connect(DB_PATH)
    copy = sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()

    try:
        os.chmod(target, 0o600)  # owner-only where the OS supports it
    except OSError:
        pass
    print(f"Backup saved: {target}")
    return target


def prune(keep):
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "brewskers-*.db")))
    for old in files[:-keep]:
        os.remove(old)
        print(f"Removed old backup: {os.path.basename(old)}")


def verify(path):
    """Open the backup read-only, run SQLite's integrity check, count rows."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        print(f"VERIFY FAILED: {result}")
        sys.exit(1)

    tables = [
        row[0] for row in db.execute(
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
    args = parser.parse_args()

    latest = make_backup()
    prune(max(1, args.keep))
    if args.verify:
        verify(latest)
