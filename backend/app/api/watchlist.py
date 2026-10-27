"""Watchlist routes: `/api/watchlist`."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import StateDep
from app.services.watchlist import (
    WatchlistView,
    add_to_watchlist,
    list_watchlist,
    remove_from_watchlist,
)
from db.models import WatchlistEntry

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistRequest(BaseModel):
    ticker: str


@router.get("")
def get_watchlist(state: StateDep) -> list[WatchlistView]:
    return list_watchlist(state)


@router.post("", status_code=201)
async def post_watchlist(body: WatchlistRequest, state: StateDep) -> WatchlistEntry:
    return await add_to_watchlist(state, body.ticker)


@router.delete("/{ticker}", status_code=204)
async def delete_watchlist(ticker: str, state: StateDep) -> None:
    await remove_from_watchlist(state, ticker)
