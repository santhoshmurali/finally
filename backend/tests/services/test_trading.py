"""Trade execution: fills, weighted average cost, cash and share limits."""

import pytest

from app.services.errors import PriceUnavailableError, RejectedError
from app.services.portfolio import build_portfolio
from app.services.snapshots import snapshot_history
from app.services.trading import execute_trade

STARTING_CASH = 1_000_000.0


async def test_buy_fills_at_cached_price_and_debits_cash(state):
    trade = await execute_trade(state, "tcs", 10, "buy")

    portfolio = build_portfolio(state)
    assert trade.ticker == "TCS"
    assert trade.price == 2500.0
    assert portfolio.cash_balance == STARTING_CASH - 25_000
    assert portfolio.positions[0].quantity == 10
    assert portfolio.positions[0].avg_cost == 2500.0


async def test_second_buy_averages_the_cost(state):
    await execute_trade(state, "TCS", 10, "buy")
    state.cache.update("TCS", 2700.0)
    await execute_trade(state, "TCS", 10, "buy")

    position = build_portfolio(state).positions[0]
    assert position.quantity == 20
    assert position.avg_cost == 2600.0


async def test_buy_beyond_cash_is_rejected(state):
    with pytest.raises(RejectedError, match="Insufficient cash"):
        await execute_trade(state, "TCS", 1000, "buy")

    assert build_portfolio(state).cash_balance == STARTING_CASH


async def test_partial_sell_keeps_average_cost_and_credits_cash(state):
    await execute_trade(state, "TCS", 10, "buy")
    state.cache.update("TCS", 2700.0)
    await execute_trade(state, "TCS", 4, "sell")

    portfolio = build_portfolio(state)
    assert portfolio.positions[0].quantity == 6
    assert portfolio.positions[0].avg_cost == 2500.0
    assert portfolio.cash_balance == STARTING_CASH - 25_000 + 4 * 2700


async def test_selling_all_shares_deletes_the_position(state):
    await execute_trade(state, "TCS", 10, "buy")
    await execute_trade(state, "TCS", 10, "sell")

    assert build_portfolio(state).positions == []


async def test_selling_more_than_held_is_rejected(state):
    await execute_trade(state, "TCS", 5, "buy")

    with pytest.raises(RejectedError, match="Insufficient shares"):
        await execute_trade(state, "TCS", 6, "sell")
    assert build_portfolio(state).positions[0].quantity == 5


async def test_selling_an_unheld_ticker_is_rejected(state):
    with pytest.raises(RejectedError, match="Insufficient shares"):
        await execute_trade(state, "INFY", 1, "sell")


async def test_unknown_ticker_is_rejected(state):
    with pytest.raises(RejectedError, match="not supported"):
        await execute_trade(state, "NOPE", 1, "buy")


async def test_ticker_without_a_price_gives_503(state):
    with pytest.raises(PriceUnavailableError) as error:
        await execute_trade(state, "SILENT", 1, "buy")

    assert error.value.status_code == 503
    assert "SILENT" not in state.cache


async def test_quantity_must_be_positive(state):
    with pytest.raises(RejectedError, match="greater than zero"):
        await execute_trade(state, "TCS", 0, "buy")


async def test_trade_records_a_snapshot(state):
    await execute_trade(state, "TCS", 10, "buy")

    history = snapshot_history(None)
    assert [snapshot.total_value for snapshot in history] == [STARTING_CASH]


async def test_unwatched_ticker_is_released_once_sold_out(state):
    await execute_trade(state, "WIPRO", 1, "buy")
    assert "WIPRO" in state.cache

    await execute_trade(state, "WIPRO", 1, "sell")
    assert "WIPRO" not in state.cache
