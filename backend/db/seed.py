"""Default profile and watchlist, inserted once on a fresh database."""

import sqlite3

from app.market import DEFAULT_WATCHLIST

from .common import DEFAULT_USER_ID, STARTING_CASH, new_id, now_iso


def seed_defaults(conn: sqlite3.Connection) -> None:
    """Insert the default profile and watchlist unless the profile already exists."""
    if has_profile(conn):
        return
    created_at = now_iso()
    conn.execute(
        "INSERT INTO users_profile (user_id, cash_balance, created_at) VALUES (?, ?, ?)",
        (DEFAULT_USER_ID, STARTING_CASH, created_at),
    )
    conn.executemany(
        "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [(new_id(), DEFAULT_USER_ID, ticker, created_at) for ticker in DEFAULT_WATCHLIST],
    )


def has_profile(conn: sqlite3.Connection) -> bool:
    """True when the default user profile row exists."""
    row = conn.execute(
        "SELECT 1 FROM users_profile WHERE user_id = ?", (DEFAULT_USER_ID,)
    ).fetchone()
    return row is not None
