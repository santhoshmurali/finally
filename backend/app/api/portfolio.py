"""Portfolio routes: valuation, trades and value history."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import TradeRequest
from app.portfolio import PortfolioService, history_window


def create_portfolio_router(portfolio: PortfolioService) -> APIRouter:
    router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    @router.get("")
    def get_portfolio() -> dict:
        return asdict(portfolio.get_portfolio())

    @router.post("/trade")
    async def post_trade(body: TradeRequest) -> dict:
        result = await portfolio.execute_trade(body.ticker, body.quantity, body.side)
        return asdict(result)

    @router.get("/history")
    def get_history(
        window: Annotated[str, Query(alias="range")] = "all",
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[dict]:
        try:
            since = history_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return portfolio.history(since, limit)

    return router
