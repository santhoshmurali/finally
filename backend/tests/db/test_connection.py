"""Connection, schema creation, seeding and the transaction helper."""

from pathlib import Path

import pytest

from app.market import DEFAULT_WATCHLIST
from db.connection import DEFAULT_DB_PATH, db_path, init_db, transaction
from db.seed import seed_defaults

EXPECTED_TABLES = {
    "users_profile",
    "watchlist",
    "positions",
    "trades",
    "portfolio_snapshots",
    "chat_messages",
}


def table_names() -> set[str]:
    with transaction() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_db_path_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "x.db"))
    assert db_path() == tmp_path / "x.db"


def test_db_path_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("FINALLY_DB_PATH", raising=False)
    assert db_path() == Path(DEFAULT_DB_PATH)


def test_init_creates_all_tables(initialized_db):
    assert EXPECTED_TABLES <= table_names()


def test_seed_sets_default_cash(initialized_db):
    with transaction() as conn:
        row = conn.execute("SELECT user_id, cash_balance FROM users_profile").fetchone()
    assert (row["user_id"], row["cash_balance"]) == ("default", 1000000.0)


def test_seed_inserts_default_watchlist_in_order(initialized_db):
    with transaction() as conn:
        rows = conn.execute("SELECT ticker FROM watchlist ORDER BY rowid").fetchall()
    assert [row["ticker"] for row in rows] == DEFAULT_WATCHLIST


def test_init_is_idempotent_and_does_not_reseed(initialized_db):
    with transaction() as conn:
        conn.execute("UPDATE users_profile SET cash_balance = 5.0")
        conn.execute("DELETE FROM watchlist WHERE ticker = 'TCS'")
    init_db()
    with transaction() as conn:
        cash = conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    assert cash == 5.0
    assert count == len(DEFAULT_WATCHLIST) - 1


def test_seed_defaults_is_a_no_op_when_profile_exists(initialized_db):
    with transaction() as conn:
        seed_defaults(conn)
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    assert count == len(DEFAULT_WATCHLIST)


def test_transaction_commits_on_success(initialized_db):
    with transaction() as conn:
        conn.execute("UPDATE users_profile SET cash_balance = 42.0")
    with transaction() as conn:
        assert conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0] == 42.0


def test_transaction_rolls_back_on_exception(initialized_db):
    with pytest.raises(RuntimeError):
        with transaction() as conn:
            conn.execute("UPDATE users_profile SET cash_balance = 42.0")
            raise RuntimeError("boom")
    with transaction() as conn:
        assert conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0] == 1000000.0
