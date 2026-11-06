"""SQL for cash, positions, trades, snapshots, watchlist and chat history.

Every function takes an open connection, so callers can group several writes
into one transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from db import DEFAULT_USER_ID, new_id, now_iso


def read_cash(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE user_id = ?", (DEFAULT_USER_ID,)
    ).fetchone()
    return float(row["cash_balance"])


def write_cash(conn: sqlite3.Connection, cash_balance: float) -> None:
    conn.execute(
        "UPDATE users_profile SET cash_balance = ? WHERE user_id = ?",
        (cash_balance, DEFAULT_USER_ID),
    )


def read_position(conn: sqlite3.Connection, ticker: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    ).fetchone()


def read_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? ORDER BY ticker",
        (DEFAULT_USER_ID,),
    ).fetchall()


def write_position(conn: sqlite3.Connection, ticker: str, quantity: float, avg_cost: float) -> None:
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
    conn.execute(
        "DELETE FROM positions WHERE user_id = ? AND ticker = ?", (DEFAULT_USER_ID, ticker)
    )


def insert_trade(
    conn: sqlite3.Connection, ticker: str, side: str, quantity: float, price: float
) -> str:
    executed_at = now_iso()
    conn.execute(
        """
        INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id(), DEFAULT_USER_ID, ticker, side, quantity, price, executed_at),
    )
    return executed_at


def insert_snapshot(conn: sqlite3.Connection, total_value: float) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (new_id(), DEFAULT_USER_ID, total_value, now_iso()),
    )


def read_snapshots(
    conn: sqlite3.Connection, since: str | None = None, limit: int | None = None
) -> list[sqlite3.Row]:
    """Snapshots oldest first. With `limit`, the newest `limit` rows are returned."""
    sql = "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ?"
    params: list[Any] = [DEFAULT_USER_ID]
    if since is not None:
        sql += " AND recorded_at >= ?"
        params.append(since)
    if limit is not None:
        sql = f"SELECT * FROM ({sql} ORDER BY recorded_at DESC LIMIT ?) ORDER BY recorded_at ASC"
        params.append(limit)
    else:
        sql += " ORDER BY recorded_at ASC"
    return conn.execute(sql, params).fetchall()


def read_watchlist_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, ticker",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [row["ticker"] for row in rows]


def insert_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    """Add `ticker`. Returns False when it was already watched."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (new_id(), DEFAULT_USER_ID, ticker, now_iso()),
    )
    return cursor.rowcount == 1


def delete_watchlist(conn: sqlite3.Connection, ticker: str) -> bool:
    """Remove `ticker`. Returns False when it was not watched."""
    cursor = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (DEFAULT_USER_ID, ticker)
    )
    return cursor.rowcount == 1


def insert_chat_message(
    conn: sqlite3.Connection, role: str, content: str, actions: dict[str, Any] | None = None
) -> None:
    conn.execute(
        """
        INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            DEFAULT_USER_ID,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            now_iso(),
        ),
    )


def read_chat_history(conn: sqlite3.Connection) -> Sequence[sqlite3.Row]:
    return conn.execute(
        "SELECT role, content, actions FROM chat_messages WHERE user_id = ? "
        "ORDER BY created_at ASC, rowid ASC",
        (DEFAULT_USER_ID,),
    ).fetchall()
