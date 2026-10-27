"""Cash balance and position repository functions."""

from db.connection import transaction
from db.positions import delete_position, get_position, list_positions, save_position
from db.profile import get_cash_balance, set_cash_balance


def test_cash_balance_starts_at_seed_value(initialized_db):
    with transaction() as conn:
        assert get_cash_balance(conn) == 1000000.0


def test_set_cash_balance_persists(initialized_db):
    with transaction() as conn:
        set_cash_balance(conn, 250.5)
    with transaction() as conn:
        assert get_cash_balance(conn) == 250.5


def test_get_position_returns_none_when_not_held(initialized_db):
    with transaction() as conn:
        assert get_position(conn, "TCS") is None


def test_save_position_inserts_then_updates(initialized_db):
    with transaction() as conn:
        save_position(conn, "TCS", 10, 2500.0)
    with transaction() as conn:
        save_position(conn, "TCS", 15, 2400.0)
    with transaction() as conn:
        position = get_position(conn, "TCS")
    assert (position.ticker, position.quantity, position.avg_cost) == ("TCS", 15, 2400.0)
    assert position.updated_at


def test_list_positions_sorted_by_ticker(initialized_db):
    with transaction() as conn:
        save_position(conn, "TCS", 1, 2500.0)
        save_position(conn, "INFY", 2, 1100.0)
    with transaction() as conn:
        tickers = [position.ticker for position in list_positions(conn)]
    assert tickers == ["INFY", "TCS"]


def test_delete_position_removes_row(initialized_db):
    with transaction() as conn:
        save_position(conn, "TCS", 1, 2500.0)
    with transaction() as conn:
        delete_position(conn, "TCS")
    with transaction() as conn:
        assert get_position(conn, "TCS") is None
        assert list_positions(conn) == []
