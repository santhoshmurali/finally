"""Trade history and watchlist repository functions."""

from db.connection import transaction
from db.trades import insert_trade, list_trades
from db.watchlist import add_watchlist, delete_watchlist, list_watchlist


def test_insert_trade_returns_and_stores_trade(initialized_db):
    with transaction() as conn:
        trade = insert_trade(conn, "TCS", "buy", 10, 2529.0)
    with transaction() as conn:
        stored = list_trades(conn)
    assert stored == [trade]
    assert (trade.ticker, trade.side, trade.quantity, trade.price) == ("TCS", "buy", 10, 2529.0)
    assert trade.id and trade.executed_at


def test_list_trades_oldest_first(initialized_db):
    with transaction() as conn:
        insert_trade(conn, "TCS", "buy", 1, 2500.0)
        insert_trade(conn, "TCS", "sell", 1, 2600.0)
    with transaction() as conn:
        assert [trade.side for trade in list_trades(conn)] == ["buy", "sell"]


def test_list_watchlist_returns_seeded_tickers(initialized_db):
    with transaction() as conn:
        tickers = [entry.ticker for entry in list_watchlist(conn)]
    assert len(tickers) == 10
    assert tickers[0] == "RELIANCE"


def test_add_watchlist_returns_false_for_duplicate(initialized_db):
    with transaction() as conn:
        assert add_watchlist(conn, "WIPRO") is True
    with transaction() as conn:
        assert add_watchlist(conn, "WIPRO") is False
        assert [entry.ticker for entry in list_watchlist(conn)].count("WIPRO") == 1


def test_delete_watchlist_returns_false_when_absent(initialized_db):
    with transaction() as conn:
        assert delete_watchlist(conn, "WIPRO") is False


def test_delete_watchlist_removes_ticker(initialized_db):
    with transaction() as conn:
        assert delete_watchlist(conn, "TCS") is True
    with transaction() as conn:
        assert "TCS" not in [entry.ticker for entry in list_watchlist(conn)]
