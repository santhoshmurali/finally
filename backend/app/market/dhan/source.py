"""DhanHQ-backed MarketDataSource (REST polling)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

from ..cache import PriceCache
from ..interface import MarketDataSource
from ..models import Bar, PriceUpdate
from .client import IST, DhanAuthError, DhanClient, DhanError, DhanRateLimited
from .instruments import Instrument, InstrumentResolver

logger = logging.getLogger(__name__)

CLOSED_POLL_INTERVAL = 30.0  # prices are static outside the session
AUTH_RETRY_INTERVAL = 60.0
MAX_BACKOFF = 30.0


def market_is_open(now: datetime | None = None) -> bool:
    """NSE cash session: 09:15-15:30 IST, Monday-Friday (holidays not modelled)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def _group(insts: list[Instrument]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for i in insts:
        grouped.setdefault(i.segment, []).append(i.security_id)
    return grouped


class DhanDataSource(MarketDataSource):
    """Polls Dhan's /marketfeed/ohlc for all tracked tickers in one call per cycle.

    Previous close comes from daily history (latest bar dated before today, IST);
    ``ohlc.close`` is used only if the history lookup for that ticker has failed.
    """

    name = "dhanhq"
    currency = "INR"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        price_cache: PriceCache,
        cache_dir: Path | str = "/app/db",
        poll_interval: float = 2.0,
        *,
        base_url: str | None = None,
        client: DhanClient | None = None,
        resolver: InstrumentResolver | None = None,
    ) -> None:
        self._cache = price_cache
        self._client = client or DhanClient(client_id, access_token, base_url=base_url)
        self._resolver = resolver or InstrumentResolver(cache_dir)
        self._interval = max(1.0, poll_interval)
        self._tickers: dict[str, Instrument] = {}
        self._prev_close: dict[str, float] = {}
        self._prev_close_tried: set[str] = set()
        self._prev_close_day: date | None = None
        self._task: asyncio.Task | None = None
        self._bg: set[asyncio.Task] = set()
        self.healthy = True

    # ---- lifecycle ----

    async def start(self, tickers: list[str]) -> None:
        await self._resolver.load()
        for t in tickers:
            self._track(t)
        self._task = asyncio.create_task(self._run_loop(), name="dhan-poll")
        logger.info("Dhan source started with %d resolvable tickers", len(self._tickers))

    async def stop(self) -> None:
        tasks = [t for t in [self._task, *self._bg] if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._bg.clear()
        await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        if self._track(ticker):
            self._spawn(self._refresh_prev_close([ticker.strip().upper()]))
            self._spawn(self._safe_poll())

    async def remove_ticker(self, ticker: str) -> None:
        t = ticker.strip().upper()
        self._tickers.pop(t, None)
        self._prev_close.pop(t, None)
        self._prev_close_tried.discard(t)
        self._cache.remove(t)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def is_supported(self, ticker: str) -> bool:
        return self._resolver.resolve(ticker) is not None

    # ---- on-demand ----

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        insts = {t.strip().upper(): self._resolver.resolve(t) for t in tickers}
        known = [i for i in insts.values() if i is not None]
        if not known:
            return {}
        raw = await self._client.ohlc(_group(known))
        out: dict[str, PriceUpdate] = {}
        for t, inst in insts.items():
            q = raw.get(inst.segment, {}).get(inst.security_id) if inst else None
            if q and q.get("last_price"):
                price = round(float(q["last_price"]), 2)
                prev = self._prev_close.get(t) or (q.get("ohlc") or {}).get("close") or None
                out[t] = PriceUpdate(t, price, price, previous_close=prev)
        return out

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        inst = self._resolver.resolve(ticker)
        if inst is None:
            return []
        return await self._client.daily_bars(
            inst.security_id, inst.segment, start, end, inst.instrument
        )

    async def get_eod_closes(
        self, tickers: list[str], on: date | None = None
    ) -> dict[str, float]:
        if on is not None:
            end = on
        else:
            today = datetime.now(IST).date()
            end = today - timedelta(days=1) if market_is_open() else today
        start = end - timedelta(days=7)  # cover weekends/holidays
        results = await asyncio.gather(
            *(self.get_daily_bars(t, start, end) for t in tickers), return_exceptions=True
        )
        out: dict[str, float] = {}
        for t, bars in zip(tickers, results, strict=True):
            if isinstance(bars, BaseException):
                logger.warning("EOD fetch failed for %s: %s", t, bars)
            elif bars:
                out[t.strip().upper()] = bars[-1].close
        return out

    # ---- internals ----

    def _track(self, ticker: str) -> bool:
        t = ticker.strip().upper()
        inst = self._resolver.resolve(t)
        if inst is None:
            logger.warning("Dhan: %s is not a known NSE equity; it will have no price", t)
            return False
        if t in self._tickers:
            return False
        self._tickers[t] = inst
        return True

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _refresh_prev_close(self, tickers: list[str]) -> None:
        today = datetime.now(IST).date()
        self._prev_close_day = today  # set first so the loop doesn't respawn us
        for t in tickers:
            inst = self._tickers.get(t)
            if inst is None:
                continue
            try:
                bars = await self._client.daily_bars(
                    inst.security_id,
                    inst.segment,
                    today - timedelta(days=10),
                    today,
                    inst.instrument,
                )
            except asyncio.CancelledError:
                raise
            except DhanError as e:
                logger.warning("Dhan: previous close for %s unavailable: %s", t, e)
                self._prev_close_tried.add(t)
                continue
            prior = [b for b in bars if b.date < today]
            if prior:
                self._prev_close[t] = prior[-1].close
            self._prev_close_tried.add(t)

    async def _safe_poll(self) -> None:
        try:
            await self._poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Dhan: immediate poll failed: %s", e)

    async def _poll_once(self) -> None:
        active = dict(self._tickers)
        if not active:
            return
        raw = await self._client.ohlc(_group(list(active.values())))
        self.healthy = True
        for t, inst in active.items():
            q = raw.get(inst.segment, {}).get(inst.security_id)
            if not q or not q.get("last_price"):
                continue  # keep last cached price; never write 0
            prev = self._prev_close.get(t)
            if prev is None and t in self._prev_close_tried:
                prev = (q.get("ohlc") or {}).get("close") or None
            self._cache.update(t, float(q["last_price"]), previous_close=prev)

    async def _run_loop(self) -> None:
        delay = self._interval
        while True:
            try:
                if datetime.now(IST).date() != self._prev_close_day:
                    self._spawn(self._refresh_prev_close(list(self._tickers)))
                await self._poll_once()
                delay = self._interval if market_is_open() else CLOSED_POLL_INTERVAL
            except asyncio.CancelledError:
                raise
            except DhanRateLimited:
                delay = min(delay * 2, MAX_BACKOFF)
                logger.warning("Dhan rate limited; next poll in %.0fs", delay)
            except DhanAuthError as e:
                if self.healthy:
                    logger.error("Dhan authentication failed (token expired?): %s", e)
                self.healthy = False
                delay = AUTH_RETRY_INTERVAL
            except Exception:
                logger.exception("Dhan poll failed")
                delay = min(max(delay, self._interval) * 2, MAX_BACKOFF)
            await asyncio.sleep(delay)
