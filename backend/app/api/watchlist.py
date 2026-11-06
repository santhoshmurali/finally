"""Watchlist routes: list, add and remove tickers."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Response, status

from app.api.schemas import WatchlistRequest
from app.watchlist import WatchlistService


def create_watchlist_router(watchlist: WatchlistService) -> APIRouter:
    router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

    @router.get("")
    def list_watchlist() -> list[dict]:
        return [asdict(entry) for entry in watchlist.list_tickers()]

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def add_to_watchlist(body: WatchlistRequest) -> dict:
        return asdict(await watchlist.add(body.ticker))

    @router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_from_watchlist(ticker: str) -> Response:
        await watchlist.remove(ticker)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
