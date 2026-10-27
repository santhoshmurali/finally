"""Portfolio view: cash, positions valued at live prices, and the totals."""

from dataclasses import dataclass

from app.state import AppState
from db.connection import transaction
from db.models import Position
from db.positions import list_positions
from db.profile import get_cash_balance

PERCENT = 100


@dataclass(frozen=True, slots=True)
class PositionView:
    """One held ticker valued at its current price."""

    ticker: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float
    day_change_percent: float


@dataclass(frozen=True, slots=True)
class PortfolioView:
    """Cash plus every position, with the totals the UI and the LLM read."""

    cash_balance: float
    total_value: float
    unrealized_pnl: float
    positions: list[PositionView]


def build_portfolio(state: AppState) -> PortfolioView:
    """Current portfolio. A position without a price yet is valued at its average cost."""
    with transaction() as conn:
        cash = get_cash_balance(conn)
        positions = [_position_view(state, position) for position in list_positions(conn)]
    market_value = sum(position.market_value for position in positions)
    return PortfolioView(
        cash_balance=cash,
        total_value=round(cash + market_value, 2),
        unrealized_pnl=round(sum(position.unrealized_pnl for position in positions), 2),
        positions=positions,
    )


def _position_view(state: AppState, position: Position) -> PositionView:
    update = state.cache.get(position.ticker)
    price = update.price if update else position.avg_cost
    pnl_per_share = price - position.avg_cost
    return PositionView(
        ticker=position.ticker,
        quantity=position.quantity,
        avg_cost=position.avg_cost,
        current_price=price,
        market_value=round(price * position.quantity, 2),
        unrealized_pnl=round(pnl_per_share * position.quantity, 2),
        unrealized_pnl_percent=round(pnl_per_share / position.avg_cost * PERCENT, 2),
        day_change_percent=update.day_change_percent if update else 0.0,
    )
