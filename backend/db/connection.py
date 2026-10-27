"""SQLite connection, schema creation and the transaction helper."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .seed import seed_defaults

DEFAULT_DB_PATH = "db/finally.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    """Database file from FINALLY_DB_PATH, relative to the backend working directory."""
    return Path(os.environ.get("FINALLY_DB_PATH", DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    """New connection with rows as mappings and foreign keys enforced."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create missing tables and seed default data. Safe to call on every start."""
    with transaction() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed_defaults(conn)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Connection that commits on success and rolls back when the block raises."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()
