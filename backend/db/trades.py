"""Trade history. Append-only: rows are never updated or deleted."""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso
from .models import Trade


def insert_trade(
    conn: sqlite3.Connection, ticker: str, side: str, quantity: float, price: float
) -> Trade:
    """Append one executed trade and return it."""
    trade = Trade(
        id=new_id(),
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        executed_at=now_iso(),
    )
    conn.execute(
        """
        INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (trade.id, DEFAULT_USER_ID, ticker, side, quantity, price, trade.executed_at),
    )
    return trade


def list_trades(conn: sqlite3.Connection) -> list[Trade]:
    """All trades in execution order, oldest first."""
    rows = conn.execute(
        """
        SELECT id, ticker, side, quantity, price, executed_at
        FROM trades WHERE user_id = ? ORDER BY rowid
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [Trade(**row) for row in rows]
