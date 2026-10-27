"""Current holdings, one row per ticker. A row is deleted when its quantity reaches zero."""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso
from .models import Position

POSITION_COLUMNS = "ticker, quantity, avg_cost, updated_at"


def list_positions(conn: sqlite3.Connection) -> list[Position]:
    """All held tickers, sorted by ticker."""
    rows = conn.execute(
        f"SELECT {POSITION_COLUMNS} FROM positions WHERE user_id = ? ORDER BY ticker",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [Position(**row) for row in rows]


def get_position(conn: sqlite3.Connection, ticker: str) -> Position | None:
    """Holding for one ticker, or None when the ticker is not held."""
    row = conn.execute(
        f"SELECT {POSITION_COLUMNS} FROM positions WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    ).fetchone()
    return None if row is None else Position(**row)


def save_position(conn: sqlite3.Connection, ticker: str, quantity: float, avg_cost: float) -> None:
    """Insert or update the holding for one ticker."""
    conn.execute(
        """
        INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, ticker) DO UPDATE SET
            quantity = excluded.quantity,
            avg_cost = excluded.avg_cost,
            updated_at = excluded.updated_at
        """,
        (new_id(), DEFAULT_USER_ID, ticker, quantity, avg_cost, now_iso()),
    )


def delete_position(conn: sqlite3.Connection, ticker: str) -> None:
    """Remove the holding for one ticker."""
    conn.execute(
        "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    )
