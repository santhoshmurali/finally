"""SQLite access: lazy schema creation, seeding, and one connection per unit of work."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_USER_ID = "default"
STARTING_CASH = 1_000_000.0
CONNECT_TIMEOUT_SECONDS = 5


def new_id() -> str:
    """A fresh UUID4 string for primary keys."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Current UTC time as ISO 8601. Fixed precision keeps string order equal to time order."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Database:
    """Opens connections to the FinAlly SQLite file.

    The schema is created and the defaults are seeded by `initialize()`. It runs
    at startup, and `connect()` runs it again if it has not happened yet, so a
    missing file or table is created on first use.
    """

    def __init__(self, path: str | Path, default_watchlist: Sequence[str]) -> None:
        self.path = Path(path)
        self.default_watchlist = tuple(default_watchlist)
        self._initialized = False

    def initialize(self) -> None:
        """Create missing tables and seed defaults. Seeds only when no profile exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=CONNECT_TIMEOUT_SECONDS)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            if (
                conn.execute(
                    "SELECT 1 FROM users_profile WHERE user_id = ?", (DEFAULT_USER_ID,)
                ).fetchone()
                is None
            ):
                self._seed(conn)
            conn.commit()
        finally:
            conn.close()
        self._initialized = True

    def _seed(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO users_profile (user_id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, STARTING_CASH, now_iso()),
        )
        conn.executemany(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            [(new_id(), DEFAULT_USER_ID, ticker, now_iso()) for ticker in self.default_watchlist],
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success, rolls back on error, and closes."""
        if not self._initialized:
            self.initialize()
        conn = sqlite3.connect(self.path, timeout=CONNECT_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
