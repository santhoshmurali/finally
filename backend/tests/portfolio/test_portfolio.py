"""Trade execution, valuation, snapshots and history of the portfolio service."""

from datetime import UTC, datetime, timedelta

import pytest

from app.market import PriceCache, UnsupportedTickerError
from app.portfolio import PortfolioService, TradeRejectedError, history_window
from db import Database
from tests.fakes import FakeSource

WATCHLIST = ("TCS", "INFY")


@pytest.fixture
def setup(tmp_path):
    prices = {"TCS": 100.0, "INFY": 50.0, "RELIANCE": 200.0}
    cache = PriceCache()
    db = Database(tmp_path / "finally.db", WATCHLIST)
    source = FakeSource(cache, prices)
    service = PortfolioService(db, cache, source)
    return service, cache, source, db, prices


def cash_of(db: Database) -> float:
    with db.connect() as conn:
        return conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0]


async def start_watched(source: FakeSource, *tickers: str) -> None:
    await source.start(list(tickers))


async def test_buy_debits_cash_and_opens_position(setup):
    service, _, source, db, _ = setup
    await start_watched(source, "TCS")

    result = await service.execute_trade("TCS", 10, "buy")

    portfolio = service.get_portfolio()
    assert result.price == 100.0
    assert result.cash_balance == 1_000_000.0 - 1000.0
    assert portfolio.cash_balance == 1_000_000.0 - 1000.0
    assert portfolio.positions[0].ticker == "TCS"
    assert portfolio.positions[0].quantity == 10
    assert portfolio.positions[0].avg_cost == 100.0


async def test_second_buy_uses_weighted_average_cost(setup):
    service, _, source, _, prices = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 10, "buy")
    prices["TCS"] = 120.0
    source.cache.update("TCS", 120.0)

    await service.execute_trade("TCS", 10, "buy")

    position = service.get_portfolio().positions[0]
    assert position.quantity == 20
    assert position.avg_cost == pytest.approx(110.0)


async def test_partial_sell_keeps_average_cost_and_credits_cash(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 10, "buy")
    source.cache.update("TCS", 130.0)

    result = await service.execute_trade("TCS", 4, "sell")

    portfolio = service.get_portfolio()
    assert result.cash_balance == pytest.approx(1_000_000.0 - 1000.0 + 520.0)
    assert portfolio.positions[0].quantity == 6
    assert portfolio.positions[0].avg_cost == 100.0


async def test_full_sell_removes_position(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 5, "buy")

    await service.execute_trade("TCS", 5, "sell")

    assert service.get_portfolio().positions == []


async def test_sell_at_a_loss_reduces_total_value(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 10, "buy")
    source.cache.update("TCS", 80.0)

    await service.execute_trade("TCS", 10, "sell")

    assert service.get_portfolio().total_value == pytest.approx(1_000_000.0 - 200.0)


async def test_insufficient_cash_is_rejected_and_leaves_no_trace(setup):
    service, _, source, db, _ = setup
    await start_watched(source, "TCS")
    before = len(service.history())

    with pytest.raises(TradeRejectedError, match="insufficient cash"):
        await service.execute_trade("TCS", 1_000_000, "buy")

    assert cash_of(db) == 1_000_000.0
    assert len(service.history()) == before


async def test_selling_more_than_held_is_rejected(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 3, "buy")

    with pytest.raises(TradeRejectedError, match="insufficient shares"):
        await service.execute_trade("TCS", 4, "sell")


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf")])
async def test_non_positive_or_non_finite_quantity_is_rejected(setup, quantity):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")

    with pytest.raises(TradeRejectedError, match="positive"):
        await service.execute_trade("TCS", quantity, "buy")


async def test_unknown_side_is_rejected(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")

    with pytest.raises(TradeRejectedError, match="side"):
        await service.execute_trade("TCS", 1, "short")


async def test_trade_on_unpriced_ticker_is_rejected(setup):
    service, _, _, _, _ = setup

    with pytest.raises(UnsupportedTickerError):
        await service.execute_trade("NOPE", 1, "buy")


async def test_sell_of_unpriced_ticker_is_rejected(setup):
    service, _, _, _, _ = setup

    with pytest.raises(TradeRejectedError, match="not priced yet"):
        await service.execute_trade("TCS", 1, "sell")


async def test_buying_unwatched_ticker_starts_pricing_and_selling_all_stops_it(setup):
    service, cache, source, _, _ = setup

    await service.execute_trade("RELIANCE", 2, "buy")
    assert source.added == ["RELIANCE"]
    assert "RELIANCE" in cache

    await service.execute_trade("RELIANCE", 2, "sell")
    assert source.removed == ["RELIANCE"]
    assert "RELIANCE" not in cache


async def test_selling_watched_ticker_keeps_it_priced(setup):
    service, cache, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 2, "buy")

    await service.execute_trade("TCS", 2, "sell")

    assert source.removed == []
    assert "TCS" in cache


async def test_rejected_buy_of_unwatched_ticker_stops_pricing_it(setup):
    service, cache, source, _, _ = setup

    with pytest.raises(TradeRejectedError):
        await service.execute_trade("RELIANCE", 1_000_000, "buy")

    assert source.removed == ["RELIANCE"]
    assert "RELIANCE" not in cache


async def test_valuation_follows_live_prices_and_day_change(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 10, "buy")
    source.cache.update("TCS", 110.0, previous_close=100.0)

    portfolio = service.get_portfolio()

    position = portfolio.positions[0]
    assert position.market_value == pytest.approx(1100.0)
    assert position.unrealized_pnl == pytest.approx(100.0)
    assert position.unrealized_pnl_percent == pytest.approx(10.0)
    assert position.day_change_percent == pytest.approx(10.0)
    assert portfolio.total_value == pytest.approx(1_000_000.0 - 1000.0 + 1100.0)


async def test_position_without_price_is_valued_at_average_cost(setup):
    service, cache, source, db, _ = setup
    await start_watched(source, "TCS")
    await service.execute_trade("TCS", 10, "buy")
    cache.remove("TCS")

    position = service.get_portfolio().positions[0]

    assert position.current_price == 100.0
    assert position.unrealized_pnl == 0.0


async def test_every_trade_and_explicit_snapshot_is_recorded(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    assert service.history() == []

    await service.execute_trade("TCS", 1, "buy")
    service.record_snapshot()

    values = [point["total_value"] for point in service.history()]
    assert len(values) == 2
    assert values[0] == pytest.approx(1_000_000.0)


async def test_history_limit_returns_newest_rows_oldest_first(setup):
    service, _, source, _, _ = setup
    await start_watched(source, "TCS")
    for _ in range(3):
        service.record_snapshot()

    rows = service.history(limit=2)

    assert len(rows) == 2
    assert rows[0]["recorded_at"] <= rows[1]["recorded_at"]


def test_history_window_maps_names_and_rejects_unknown():
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

    assert history_window("1h", now) == now - timedelta(hours=1)
    assert history_window("7d", now) == now - timedelta(days=7)
    assert history_window("all", now) is None
    with pytest.raises(ValueError):
        history_window("5y", now)
