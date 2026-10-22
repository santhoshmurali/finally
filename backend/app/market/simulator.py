"""GBM-based market simulator."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import date, timedelta

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .models import Bar, PriceUpdate
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    GROUP_CORR,
    SEED_PRICES,
    TICKER_PARAMS,
    TICKER_PATTERN,
    TSLA_CORR,
    derived_seed_price,
)
from .synthetic_history import (
    HISTORY_LOOKBACK_DAYS,
    last_trading_day_before,
    synth_daily_bars,
)

logger = logging.getLogger(__name__)

_TICKER_RE = re.compile(TICKER_PATTERN)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)

    Where:
        S(t)   = current price
        mu     = annualized drift (expected return)
        sigma  = annualized volatility
        dt     = time step as fraction of a trading year
        Z      = correlated standard normal random variable

    The tiny dt (~8.5e-8 for 500ms ticks over 252 trading days * 6.5h/day)
    produces sub-cent moves per tick that accumulate naturally over time.
    """

    # 500ms expressed as a fraction of a trading year
    # 252 trading days * 6.5 hours/day * 3600 seconds/hour = 5,896,800 seconds
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
        rng: np.random.Generator | None = None,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._rng = rng if rng is not None else np.random.default_rng()

        # Per-ticker state
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}

        # Cholesky decomposition of the correlation matrix (for correlated moves)
        self._cholesky: np.ndarray | None = None

        # Initialize all starting tickers
        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    # --- Public API ---

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        This is the hot path — called every 500ms. Keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        # Generate n independent standard normal draws
        z_independent = self._rng.standard_normal(n)

        # Apply Cholesky to get correlated draws
        if self._cholesky is not None:
            z_correlated = self._cholesky @ z_independent
        else:
            z_correlated = z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            params = self._params[ticker]
            mu = params["mu"]
            sigma = params["sigma"]

            # GBM: S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event: ~0.1% chance per tick per ticker
            # With 10 tickers at 2 ticks/sec, expect an event ~every 50 seconds
            if self._rng.random() < self._event_prob:
                shock_magnitude = self._rng.uniform(0.02, 0.05)
                shock_sign = 1 if self._rng.random() < 0.5 else -1
                self._prices[ticker] *= 1 + shock_magnitude * shock_sign
                logger.debug(
                    "Random event on %s: %.1f%% %s",
                    ticker,
                    shock_magnitude * 100,
                    "up" if shock_sign > 0 else "down",
                )

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the simulation. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the simulation. Rebuilds the correlation matrix."""
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        """Current price for a ticker, or None if not tracked."""
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        """Return the list of currently tracked tickers."""
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add a ticker without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker) or derived_seed_price(ticker)
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition of the ticker correlation matrix.

        Called whenever tickers are added or removed. O(n^2) but n < 50. If the
        matrix is not positive-definite it is shrunk toward the identity until it
        factorises; as a last resort moves become independent.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        for _ in range(10):
            try:
                self._cholesky = np.linalg.cholesky(corr)
                return
            except np.linalg.LinAlgError:
                corr = 0.9 * corr + 0.1 * np.eye(n)
        self._cholesky = None

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Determine correlation between two tickers based on sector grouping.

        Correlation structure:
          - Same group (tech, finance, in_it, in_banks): the group's correlation
          - TSLA with anything: 0.3 (it does its own thing)
          - Cross-sector / unknown tickers: 0.3
        """
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR

        for group, members in CORRELATION_GROUPS.items():
            if t1 in members and t2 in members:
                return GROUP_CORR.get(group, CROSS_GROUP_CORR)

        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM simulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to the PriceCache. The seed
    price of each ticker is its previous close, so day change starts at 0%.
    """

    name = "simulator"
    currency = "USD"

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
        seed: int | None = None,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._seed = seed
        self._sim: GBMSimulator | None = None
        self._prev_close: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(
            tickers=tickers,
            dt=self._interval / GBMSimulator.TRADING_SECONDS_PER_YEAR,
            event_probability=self._event_prob,
            rng=np.random.default_rng(self._seed),
        )
        # Seed the cache with initial prices so SSE has data immediately
        for ticker in tickers:
            self._seed_cache(ticker)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info(
            "Simulator started with %d tickers (seed=%s)", len(tickers), self._seed
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            self._seed_cache(ticker)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._prev_close.pop(ticker, None)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    # --- on-demand API ---

    async def is_supported(self, ticker: str) -> bool:
        return bool(_TICKER_RE.fullmatch(ticker.strip().upper()))

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        out: dict[str, PriceUpdate] = {}
        for t in (x.strip().upper() for x in tickers):
            update = self._cache.get(t)
            if update is not None:
                out[t] = update
            elif await self.is_supported(t):
                p = self._anchor_price(t)
                out[t] = PriceUpdate(t, p, p, previous_close=p)
        return out

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        t = ticker.strip().upper()
        if not await self.is_supported(t):
            return []
        params = TICKER_PARAMS.get(t, DEFAULT_PARAMS)
        last_session = last_trading_day_before(date.today())
        # Fixed lookback keeps the series identical across calls; callers slice it.
        bars = synth_daily_bars(
            t,
            last_session,
            HISTORY_LOOKBACK_DAYS,
            self._anchor_price(t),
            mu=params["mu"],
            sigma=params["sigma"],
        )
        return [b for b in bars if start <= b.date <= end]

    async def get_eod_closes(
        self, tickers: list[str], on: date | None = None
    ) -> dict[str, float]:
        day = on or last_trading_day_before(date.today())
        out: dict[str, float] = {}
        for t in tickers:
            bars = await self.get_daily_bars(t, day - timedelta(days=7), day)
            if bars:
                out[t.strip().upper()] = bars[-1].close
        return out

    # --- internals ---

    def _anchor_price(self, ticker: str) -> float:
        return (
            self._prev_close.get(ticker)
            or SEED_PRICES.get(ticker)
            or derived_seed_price(ticker)
        )

    def _seed_cache(self, ticker: str) -> None:
        """Record the previous close and write the first price for a ticker."""
        if self._sim is None:
            return
        price = self._sim.get_price(ticker)
        if price is None:
            return
        self._prev_close.setdefault(ticker, price)
        self._cache.update(ticker=ticker, price=price, previous_close=self._prev_close[ticker])

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(
                            ticker=ticker,
                            price=price,
                            previous_close=self._prev_close.get(ticker),
                        )
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
