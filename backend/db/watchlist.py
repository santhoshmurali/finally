"""Watchlist tickers of the default user."""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso
from .models import WatchlistEntry


def list_watchlist(conn: sqlite3.Connection) -> list[WatchlistEntry]:
    """Watched tickers in the order they were added."""
    rows = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY rowid",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [WatchlistEntry(**row) for row in rows]


def add_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    """Add a ticker. Returns False when it is already on the watchlist."""
    cursor = conn.execute(
        """
        INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)
        ON CONFLICT (user_id, ticker) DO NOTHING
        """,
        (new_id(), DEFAULT_USER_ID, ticker, now_iso()),
    )
    return cursor.rowcount == 1


def delete_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    """Remove a ticker. Returns False when it was not on the watchlist."""
    cursor = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    )
    return cursor.rowcount == 1
