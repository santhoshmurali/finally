"""DhanDataSource: live NSE prices over the Dhan WebSocket feed, history over REST."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx

from ..cache import PriceCache
from ..interface import MarketDataSource
from ..models import Bar
from .auth import Credentials
from .client import DhanClient
from .feed import DhanFeed
from .instruments import SEGMENT, InstrumentResolver
from .packets import Packet, PreviousClose, Tick


class DhanDataSource(MarketDataSource):
    """Prices NSE equities in INR.

    The feed pushes a last price and previous close for each subscribed ticker
    right after subscribing (also when the market is closed), so the cache is
    populated within a second of `start`.
    """

    def __init__(
        self,
        cache: PriceCache,
        credentials: Credentials,
        *,
        resolver: InstrumentResolver | None = None,
        client: DhanClient | None = None,
        feed: DhanFeed | None = None,
    ) -> None:
        super().__init__(cache)
        self._resolver = resolver
        self._client = client or DhanClient(credentials)
        self._feed = feed or DhanFeed(credentials, self._on_packet)
        self._tickers: set[str] = set()
        self._previous_close: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        if self._resolver is None:
            async with httpx.AsyncClient() as http:
                self._resolver = await InstrumentResolver.download(http)
        security_ids = [self._resolver.security_id(t) for t in tickers]  # fail on unknown first
        self._tickers = {t.upper() for t in tickers}
        await self._feed.subscribe(security_ids)
        self._task = asyncio.create_task(self._feed.run(), name="dhan-feed")

    async def stop(self) -> None:
        await self._feed.stop()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._client.close()

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        security_id = self._resolver.security_id(ticker)
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        await self._feed.subscribe([security_id])

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._tickers:
            return
        self._tickers.discard(ticker)
        self._previous_close.pop(ticker, None)
        self.cache.remove(ticker)
        await self._feed.unsubscribe([self._resolver.security_id(ticker)])

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    async def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        return await self._client.daily_bars(self._resolver.security_id(ticker), start, end)

    def healthy(self) -> bool:
        task_alive = self._task is not None and not self._task.done()
        return task_alive and self._feed.healthy

    def _on_packet(self, packet: Packet) -> None:
        """Feed callback: turn packets into cache writes."""
        if isinstance(packet, (Tick, PreviousClose)) and packet.segment == SEGMENT:
            ticker = self._resolver.ticker(packet.security_id)
            if ticker not in self._tickers:
                return
            if isinstance(packet, Tick):
                close = self._previous_close.get(ticker)
                self.cache.update(ticker, packet.price, previous_close=close)
            else:
                self._previous_close[ticker] = packet.price
                self.cache.set_previous_close(ticker, packet.price)
