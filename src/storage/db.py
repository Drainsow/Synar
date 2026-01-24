import sqlite3
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "synar.db"
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Good defaults
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")  # better for concurrency
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS schema_migrations (
                 id TEXT PRIMARY KEY,
                 applied_at INTEGER NOT NULL)
                 """)
    
    applied = {
        row["id"] for row in conn.execute("SELECT id FROM schema_migrations")
    }

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for path in files:
        mig_id = path.stem
        if mig_id in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (mig_id, int(time.time()))
        )
        conn.commit()


def init_db() -> None:
    conn = get_connection()
    try:
        run_migrations(conn)
    finally:
        conn.close()