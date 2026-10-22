"""Market simulator: correlated geometric Brownian motion with random shock events."""

from __future__ import annotations

import asyncio
import math
from datetime import date

import numpy as np

from .cache import PriceCache
from .errors import UnsupportedTickerError
from .interface import MarketDataSource
from .models import Bar
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORRELATION,
    DEFAULT_PARAMS,
    INTRA_GROUP_CORRELATION,
    TICKER_PARAMS,
    TICKER_PATTERN,
    seed_price_for,
)
from .synthetic_history import synthetic_bars

UPDATE_INTERVAL = 0.5
NSE_TRADING_SECONDS_PER_YEAR = 252 * 6.25 * 3600
EVENT_PROBABILITY = 0.001  # per ticker per step: about one shock a minute across ten tickers
EVENT_RANGE = (0.02, 0.05)


class GBMSimulator:
    """Steps a set of tickers forward in time with correlated GBM moves."""

    def __init__(
        self, tickers: list[str], dt: float | None = None, seed: int | None = None
    ) -> None:
        self._rng = np.random.default_rng(seed)
        self._dt = dt if dt is not None else UPDATE_INTERVAL / NSE_TRADING_SECONDS_PER_YEAR
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._cholesky: np.ndarray | None = None
        for ticker in tickers:
            self._insert(ticker)
        self._rebuild_correlation()

    @property
    def tickers(self) -> list[str]:
        return list(self._tickers)

    def step(self) -> dict[str, float]:
        """Advance every ticker by one time step and return the new prices."""
        if not self._tickers:
            return {}
        shocks = self._rng.standard_normal(len(self._tickers))
        if self._cholesky is not None:
            shocks = self._cholesky @ shocks
        for i, ticker in enumerate(self._tickers):
            params = TICKER_PARAMS.get(ticker, DEFAULT_PARAMS)
            drift = (params["mu"] - 0.5 * params["sigma"] ** 2) * self._dt
            diffusion = params["sigma"] * math.sqrt(self._dt) * shocks[i]
            price = self._prices[ticker] * math.exp(drift + diffusion)
            if self._rng.random() < EVENT_PROBABILITY:
                magnitude = self._rng.uniform(*EVENT_RANGE)
                price *= 1 + magnitude * self._rng.choice([-1, 1])
            self._prices[ticker] = price
        return {t: round(p, 2) for t, p in self._prices.items()}

    def add_ticker(self, ticker: str) -> float:
        """Add `ticker` (idempotent) and return its current price."""
        if ticker not in self._prices:
            self._insert(ticker)
            self._rebuild_correlation()
        return round(self._prices[ticker], 2)

    def remove_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            self._tickers.remove(ticker)
            del self._prices[ticker]
            self._rebuild_correlation()

    def _insert(self, ticker: str) -> None:
        self._tickers.append(ticker)
        self._prices[ticker] = seed_price_for(ticker)

    def _rebuild_correlation(self) -> None:
        """Cholesky factor of the pairwise correlation matrix of the current tickers."""
        n = len(self._tickers)
        if n < 2:
            self._cholesky = None
            return
        matrix = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                matrix[i, j] = matrix[j, i] = _correlation(self._tickers[i], self._tickers[j])
        self._cholesky = np.linalg.cholesky(matrix)


def _correlation(a: str, b: str) -> float:
    for group in CORRELATION_GROUPS.values():
        if a in group and b in group:
            return INTRA_GROUP_CORRELATION
    return CROSS_GROUP_CORRELATION


class SimulatorDataSource(MarketDataSource):
    """Unified-interface wrapper that publishes simulator steps into the cache."""

    def __init__(
        self,
        cache: PriceCache,
        update_interval: float = UPDATE_INTERVAL,
        seed: int | None = None,
    ) -> None:
        super().__init__(cache)
        self._interval = update_interval
        self._seed = seed
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        tickers = [_validated(t) for t in tickers]
        self._sim = GBMSimulator(tickers, seed=self._seed)
        for ticker in tickers:
            self._seed_cache(ticker)
        self._task = asyncio.create_task(self._run(), name="simulator")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = _validated(ticker)
        if ticker not in self.get_tickers():
            self._seed_cache(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if self._sim is not None:
            self._sim.remove_ticker(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._sim.tickers) if self._sim else []

    async def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        ticker = _validated(ticker)
        return synthetic_bars(ticker, start, end, seed_price_for(ticker))

    def healthy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _seed_cache(self, ticker: str) -> None:
        price = self._sim.add_ticker(ticker)
        self.cache.update(ticker, price, previous_close=price)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            for ticker, price in self._sim.step().items():
                self.cache.update(ticker, price)


def _validated(ticker: str) -> str:
    ticker = ticker.upper()
    if not TICKER_PATTERN.match(ticker):
        raise UnsupportedTickerError(f"{ticker!r} is not a valid ticker symbol")
    return ticker
