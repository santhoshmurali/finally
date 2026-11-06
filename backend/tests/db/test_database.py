"""Schema creation, seeding and connection behaviour of the FinAlly database."""

import sqlite3

import pytest

from db import DEFAULT_USER_ID, STARTING_CASH, Database

WATCHLIST = ("RELIANCE", "TCS", "INFY")


@pytest.fixture
def database(tmp_path) -> Database:
    return Database(tmp_path / "nested" / "finally.db", WATCHLIST)


def table_names(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def test_initialize_creates_parent_dir_and_all_tables(database):
    database.initialize()

    assert database.path.exists()
    assert table_names(database.path) >= {
        "users_profile",
        "watchlist",
        "positions",
        "trades",
        "portfolio_snapshots",
        "chat_messages",
    }


def test_initialize_seeds_default_cash_and_watchlist(database):
    database.initialize()

    with database.connect() as conn:
        cash = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE user_id = ?", (DEFAULT_USER_ID,)
        ).fetchone()["cash_balance"]
        tickers = [
            row["ticker"] for row in conn.execute("SELECT ticker FROM watchlist ORDER BY ticker")
        ]

    assert cash == STARTING_CASH
    assert tickers == sorted(WATCHLIST)


def test_initialize_does_not_reseed_after_watchlist_edit(database):
    database.initialize()
    with database.connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = 'TCS'")

    database.initialize()

    with database.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    assert count == len(WATCHLIST) - 1


def test_connect_initializes_missing_database_on_first_use(database):
    with database.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]

    assert count == len(WATCHLIST)


def test_connect_rolls_back_when_block_raises(database):
    database.initialize()

    with pytest.raises(RuntimeError):
        with database.connect() as conn:
            conn.execute("UPDATE users_profile SET cash_balance = 0")
            raise RuntimeError("boom")

    with database.connect() as conn:
        cash = conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0]
    assert cash == STARTING_CASH
