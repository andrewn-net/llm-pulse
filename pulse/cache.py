import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import DB_PATH, ensure_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_fetches (
    source TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_snapshots (
    snapshot_at TEXT NOT NULL,
    category TEXT NOT NULL,
    rank INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    rating REAL NOT NULL,
    rating_lower REAL,
    rating_upper REAL,
    PRIMARY KEY (snapshot_at, category, model_name)
);
CREATE INDEX IF NOT EXISTS arena_snapshots_cat_time
    ON arena_snapshots (category, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS openrouter_snapshots (
    snapshot_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    name TEXT,
    context_length INTEGER,
    input_per_mtok_usd REAL,
    output_per_mtok_usd REAL,
    modality TEXT,
    PRIMARY KEY (snapshot_at, model_id)
);
CREATE INDEX IF NOT EXISTS openrouter_snapshots_time
    ON openrouter_snapshots (snapshot_at DESC);

CREATE TABLE IF NOT EXISTS aliases (
    arena_name TEXT PRIMARY KEY,
    openrouter_id TEXT NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    ensure_data_dir()
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_fresh(conn: sqlite3.Connection, source: str, ttl_hours: float) -> bool:
    row = conn.execute(
        "SELECT fetched_at FROM source_fetches WHERE source = ?", (source,)
    ).fetchone()
    if not row:
        return False
    fetched = datetime.fromisoformat(row["fetched_at"])
    return datetime.now(timezone.utc) - fetched < timedelta(hours=ttl_hours)


def mark_fetched(conn: sqlite3.Connection, source: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO source_fetches (source, fetched_at) VALUES (?, ?)",
        (source, now_iso()),
    )


def latest_snapshot_at(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(f"SELECT MAX(snapshot_at) AS s FROM {table}").fetchone()
    return row["s"] if row and row["s"] else None


def snapshot_at_or_before(
    conn: sqlite3.Connection, table: str, when: datetime
) -> str | None:
    row = conn.execute(
        f"SELECT MAX(snapshot_at) AS s FROM {table} WHERE snapshot_at <= ?",
        (when.isoformat(timespec="seconds"),),
    ).fetchone()
    return row["s"] if row and row["s"] else None


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )
