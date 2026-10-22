"""The unified market data interface every price source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from .cache import PriceCache
from .models import Bar


class MarketDataSource(ABC):
    """A producer of live prices and daily history.

    A source owns a background task that writes `PriceUpdate`s into `cache`.
    Consumers (SSE, trades, watchlist) only touch the cache and these methods,
    so the simulator and Dhan are interchangeable.
    """

    currency = "INR"

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing prices for `tickers`. Raises on bad credentials or symbols."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release connections. Safe to call twice."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start pricing `ticker`. Raises `UnsupportedTickerError` if unknown. Idempotent."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop pricing `ticker` and drop it from the cache. Idempotent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently priced."""

    @abstractmethod
    async def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Completed daily candles for `start <= day <= end`, oldest first."""

    @abstractmethod
    def healthy(self) -> bool:
        """False when the source cannot deliver prices (feed down, auth failed)."""
