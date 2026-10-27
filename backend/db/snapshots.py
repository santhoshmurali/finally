"""Portfolio value history for the P&L chart."""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso
from .models import Snapshot

# SQLite treats a negative LIMIT as "no limit".
NO_LIMIT = -1


def insert_snapshot(conn: sqlite3.Connection, total_value: float) -> None:
    """Record the portfolio value at the current time."""
    conn.execute(
        """
        INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at)
        VALUES (?, ?, ?, ?)
        """,
        (new_id(), DEFAULT_USER_ID, total_value, now_iso()),
    )


def list_snapshots(conn: sqlite3.Connection, limit: int | None) -> list[Snapshot]:
    """Snapshots oldest first. With a limit, keeps only the newest `limit` of them."""
    rows = conn.execute(
        """
        SELECT total_value, recorded_at FROM portfolio_snapshots
        WHERE user_id = ? ORDER BY rowid DESC LIMIT ?
        """,
        (DEFAULT_USER_ID, NO_LIMIT if limit is None else limit),
    ).fetchall()
    return [Snapshot(**row) for row in reversed(rows)]
