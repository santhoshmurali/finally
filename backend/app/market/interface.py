"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from .models import Bar, PriceUpdate


class MarketDataError(Exception):
    """Base class for market-data failures surfaced to callers."""


class CapabilityError(MarketDataError):
    """This source cannot do what was asked."""


class UnknownTickerError(MarketDataError):
    """Ticker cannot be priced by the active source."""


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Streaming consumers read from the cache; request/response
    helpers (``is_supported``, ``get_quotes``, ``get_daily_bars``,
    ``get_eod_closes``) serve validation, one-off quotes and end-of-day data.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app runs ...
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        # ... app shutting down ...
        await source.stop()
    """

    name: str = "unknown"  # "dhanhq" | "simulator" | "massive"
    currency: str = "USD"  # ISO code the prices are quoted in

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once. Calling start() twice is undefined behavior.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Safe to call multiple times. After stop(), the source will not write
        to the cache again.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        The next update cycle will include this ticker.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from the PriceCache.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""

    async def is_supported(self, ticker: str) -> bool:
        """True if this source can price ``ticker``. Cheap; no network."""
        return True

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """Latest price for many tickers in one shot. Unsupported tickers are omitted.

        Does not require the tickers to be streaming and does not write to the cache.
        """
        raise CapabilityError(f"{self.name} does not support get_quotes")

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Daily OHLCV bars for ``start <= trading date <= end``, ascending. May be empty."""
        raise CapabilityError(f"{self.name} does not support get_daily_bars")

    async def get_eod_closes(
        self, tickers: list[str], on: date | None = None
    ) -> dict[str, float]:
        """Closing price per ticker on trading date ``on`` (default: latest completed session).

        Tickers without data are omitted.
        """
        raise CapabilityError(f"{self.name} does not support get_eod_closes")
