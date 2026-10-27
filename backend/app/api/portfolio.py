"""Portfolio routes: `/api/portfolio`, trades and value history."""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import StateDep
from app.services.portfolio import PortfolioView, build_portfolio
from app.services.snapshots import snapshot_history
from app.services.trading import execute_trade
from db.models import Snapshot, Trade

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    side: Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class TradeResult:
    """The executed trade and the portfolio right after it."""

    trade: Trade
    portfolio: PortfolioView


@router.get("")
def get_portfolio(state: StateDep) -> PortfolioView:
    return build_portfolio(state)


@router.post("/trade")
async def post_trade(body: TradeRequest, state: StateDep) -> TradeResult:
    trade = await execute_trade(state, body.ticker, body.quantity, body.side)
    return TradeResult(trade=trade, portfolio=build_portfolio(state))


@router.get("/history")
def get_history(
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[Snapshot]:
    return snapshot_history(limit)
