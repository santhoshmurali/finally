"""Portfolio view: totals, unrealized P&L and the fallback price for unpriced holdings."""

from app.services.portfolio import build_portfolio
from app.services.trading import execute_trade


async def test_totals_and_pnl_follow_the_live_price(state):
    await execute_trade(state, "TCS", 10, "buy")
    state.cache.update("TCS", 2700.0)

    portfolio = build_portfolio(state)
    position = portfolio.positions[0]
    assert position.current_price == 2700.0
    assert position.market_value == 27_000.0
    assert position.unrealized_pnl == 2_000.0
    assert position.unrealized_pnl_percent == 8.0
    assert position.day_change_percent == 8.0
    assert portfolio.unrealized_pnl == 2_000.0
    assert portfolio.total_value == 975_000.0 + 27_000.0


async def test_position_without_a_price_is_valued_at_cost(state):
    await execute_trade(state, "TCS", 10, "buy")
    state.cache.remove("TCS")

    position = build_portfolio(state).positions[0]
    assert position.current_price == 2500.0
    assert position.market_value == 25_000.0
    assert position.unrealized_pnl == 0.0
    assert position.day_change_percent == 0.0
