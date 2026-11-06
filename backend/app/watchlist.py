"""Watchlist CRUD: which tickers the user follows and the source prices."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.market import MarketDataSource, PriceCache
from app.priced_set import release_if_unused
from app.repository import delete_watchlist, insert_watchlist, read_watchlist_tickers
from db import Database

TICKER_PATTERN = re.compile(r"^[A-Z0-9&-]{1,20}$")


class WatchlistError(Exception):
    """Base class for watchlist rule violations."""


class InvalidTickerError(WatchlistError):
    """The ticker text is not a plausible symbol."""


class AlreadyWatchedError(WatchlistError):
    """The ticker is already on the watchlist."""


class NotWatchedError(WatchlistError):
    """The ticker is not on the watchlist."""


@dataclass(frozen=True, slots=True)
class WatchedTicker:
    ticker: str
    price: float | None
    previous_price: float | None
    day_change_percent: float | None
    direction: str | None


class WatchlistService:
    def __init__(self, db: Database, cache: PriceCache, source: MarketDataSource) -> None:
        self.db = db
        self.cache = cache
        self.source = source

    def list_tickers(self) -> list[WatchedTicker]:
        with self.db.connect() as conn:
            tickers = read_watchlist_tickers(conn)
        return [self._view(ticker) for ticker in tickers]

    async def add(self, ticker: str) -> WatchedTicker:
        """Watch `ticker`. The source rejects unknown symbols before anything is stored."""
        symbol = normalize_ticker(ticker)
        with self.db.connect() as conn:
            if symbol in read_watchlist_tickers(conn):
                raise AlreadyWatchedError(f"{symbol} is already on the watchlist")
        await self.source.add_ticker(symbol)
        with self.db.connect() as conn:
            insert_watchlist(conn, symbol)
        return self._view(symbol)

    async def remove(self, ticker: str) -> None:
        """Stop watching `ticker`. It keeps being priced while it is held."""
        symbol = normalize_ticker(ticker)
        with self.db.connect() as conn:
            if not delete_watchlist(conn, symbol):
                raise NotWatchedError(f"{symbol} is not on the watchlist")
        await release_if_unused(self.db, self.source, symbol)

    def _view(self, ticker: str) -> WatchedTicker:
        update = self.cache.get(ticker)
        if update is None:
            return WatchedTicker(ticker, None, None, None, None)
        return WatchedTicker(
            ticker=ticker,
            price=update.price,
            previous_price=update.previous_price,
            day_change_percent=update.day_change_percent,
            direction=update.direction,
        )


def normalize_ticker(ticker: str) -> str:
    """Upper-case and trim a ticker, rejecting anything that is not a symbol shape."""
    symbol = ticker.strip().upper()
    if not TICKER_PATTERN.fullmatch(symbol):
        raise InvalidTickerError(f"{ticker!r} is not a valid ticker symbol")
    return symbol
