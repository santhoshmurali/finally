"""Watchlist: the tickers the user follows, with their live prices."""

from dataclasses import dataclass

from app.services.errors import NotFoundError, RejectedError
from app.services.priced import release_if_unused, track_ticker
from app.state import AppState
from db.connection import transaction
from db.models import WatchlistEntry
from db.watchlist import add_watchlist, delete_watchlist
from db.watchlist import list_watchlist as list_watchlist_entries


@dataclass(frozen=True, slots=True)
class WatchlistView:
    """One watched ticker. The price fields stay null until the ticker has a price."""

    ticker: str
    added_at: str
    price: float | None
    previous_close: float | None
    day_change_percent: float | None


def list_watchlist(state: AppState) -> list[WatchlistView]:
    """Watched tickers, oldest first, with prices from the cache."""
    with transaction() as conn:
        entries = list_watchlist_entries(conn)
    return [_watchlist_view(state, entry) for entry in entries]


async def add_to_watchlist(state: AppState, ticker: str) -> WatchlistEntry:
    """Watch `ticker`. Raises `RejectedError` if it is unsupported or already watched."""
    ticker = ticker.upper()
    await track_ticker(state, ticker)
    with transaction() as conn:
        if not add_watchlist(conn, ticker):
            raise RejectedError(f"{ticker} is already on the watchlist")
        return next(entry for entry in list_watchlist_entries(conn) if entry.ticker == ticker)


async def remove_from_watchlist(state: AppState, ticker: str) -> None:
    """Stop watching `ticker`. Raises `NotFoundError` if it is not on the watchlist."""
    ticker = ticker.upper()
    with transaction() as conn:
        if not delete_watchlist(conn, ticker):
            raise NotFoundError(f"{ticker} is not on the watchlist")
    await release_if_unused(state, ticker)


def _watchlist_view(state: AppState, entry: WatchlistEntry) -> WatchlistView:
    update = state.cache.get(entry.ticker)
    if update is None:
        return WatchlistView(entry.ticker, entry.added_at, None, None, None)
    return WatchlistView(
        ticker=entry.ticker,
        added_at=entry.added_at,
        price=update.price,
        previous_close=update.previous_close,
        day_change_percent=update.day_change_percent,
    )
