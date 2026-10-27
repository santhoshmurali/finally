"""Keeps the market source's priced set in step with the watchlist and the holdings."""

from app.market import UnsupportedTickerError
from app.services.errors import RejectedError
from app.state import AppState
from db.connection import transaction
from db.positions import get_position
from db.watchlist import list_watchlist


async def track_ticker(state: AppState, ticker: str) -> None:
    """Start pricing `ticker`. Raises `RejectedError` when the source does not know it."""
    try:
        await state.source.add_ticker(ticker)
    except UnsupportedTickerError as exc:
        raise RejectedError(str(exc)) from exc


async def release_if_unused(state: AppState, ticker: str) -> None:
    """Stop pricing `ticker` when it is neither on the watchlist nor held."""
    with transaction() as conn:
        watched = any(entry.ticker == ticker for entry in list_watchlist(conn))
        held = get_position(conn, ticker) is not None
    if not watched and not held:
        await state.source.remove_ticker(ticker)
