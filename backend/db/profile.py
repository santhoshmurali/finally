"""Cash balance of the default user."""

import sqlite3

from .common import DEFAULT_USER_ID


def get_cash_balance(conn: sqlite3.Connection) -> float:
    """Current cash in INR."""
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE user_id = ?", (DEFAULT_USER_ID,)
    ).fetchone()
    return row["cash_balance"]


def set_cash_balance(conn: sqlite3.Connection, amount: float) -> None:
    """Replace the cash balance in INR."""
    conn.execute(
        "UPDATE users_profile SET cash_balance = ? WHERE user_id = ?",
        (amount, DEFAULT_USER_ID),
    )
