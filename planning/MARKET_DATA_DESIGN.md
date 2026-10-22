# Market Data Backend: Detailed Design

Implementation-ready design for FinAlly's market data layer: the **Unified API**, the **Simulator**, and the **DhanHQ** source. It supersedes the code sketches in [MARKET_INTERFACE.md](MARKET_INTERFACE.md) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md), which remain the *why* (requirements, rationale, open questions); this document is the *how*. API facts come from [DHANHQ_API.md](DHANHQ_API.md); product requirements from [PLAN.md](PLAN.md) §6, §8.

> **Every code block below is the content of a file that was run, not pseudocode.** The design was implemented in a scratch copy of `backend/` and exercised there: the 73 existing market tests still pass unmodified, and 154 new tests were added (**227 passing, stable over 5 consecutive runs, `ruff` clean, 96% line coverage of `app/market`**). The Dhan client and instrument resolver were also run against the live Dhan endpoints (without credentials) to confirm the instrument list loads and that **both** real error-body shapes map to the right exception. Nothing has been written to `backend/` yet; §14 is the step-by-step plan to apply it.

**What is and is not verified**

| Verified (tests and/or live probes) | Not verifiable without a Dhan token |
|---|---|
| Simulator behaviour, determinism, history, previous close, correlation fallback | Real success-path payloads of `/marketfeed/*` and `/charts/historical` (taken from the official docs' examples) |
| Dhan client request shapes, chunking, throttling, both error shapes (**also against live Dhan**) | `ohlc.close` semantics; whether today's partial candle is returned (design is safe either way, §7.6) |
| Instrument list parsing against the **live** list (2,732 NSE equities, IDs for the 10 default tickers) | Live WebSocket ticks (parser verified against the documented layouts and a local WebSocket server) |
| Feed reconnect/resubscribe/backoff against a real local WebSocket server | Sandbox candle quality; US-stock feed |
| Service, routes, SSE payload, factory precedence, FastAPI wiring on a running server | |

---

## 1. Scope and decisions

### 1.1 Requirements → components

| PLAN / project requirement | Component | Section |
|---|---|---|
| Simulator by default, real data if a key is set (§5, §6) | `create_market_data_source()` factory | §8 |
| One interface, downstream code agnostic (§6) | `MarketDataSource` ABC | §4.4 |
| Shared price cache; SSE reads it (§6) | `PriceCache`, `stream.py` (unchanged) | §4.3 |
| GBM, correlated moves, 2-5% events, ~500 ms, seed prices (§6) | `GBMSimulator`, `SimulatorDataSource` | §5 |
| Previous close = seed price; % change vs previous close (§6, §2) | `PriceUpdate.previous_close` | §4.2 |
| **Priced tickers = watchlist ∪ held** receive prices (§1, §6) | `MarketDataService.sync()` | §9 |
| Unsupported tickers are rejected (§8) | `MarketDataSource.is_supported()` | §4.4, §10 |
| Real-time prices, many tickers | Dhan REST poll (default) / WebSocket (opt-in) | §7 |
| **End-of-day prices, many tickers** | `get_daily_bars()`, `get_eod_closes()` | §4.4, §5.4, §7 |
| Trades fill at the current price (§9) | `MarketDataService.price_for_trade()` | §9 |
| Health check (§8) | `service.status()` → `/api/health` | §9, §10 |
| No keys needed, reproducible E2E/tests (§12) | Seedable simulator (`MARKET_SEED`) | §5.1 |

### 1.2 Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Keep the **push-into-cache** architecture; sources write, consumers read the cache | Already built and tested; SSE and valuation stay source-agnostic |
| D2 | Add a separate **on-demand** surface (`get_quotes`, `get_daily_bars`, `get_eod_closes`, `is_supported`) to the same ABC | Validation, history and snapshots are request/response, not streams |
| D3 | New methods are **concrete and raise `CapabilityError`** by default | The legacy Massive source keeps working untouched |
| D4 | `PriceUpdate` carries **two** "previous" values: `previous_price` (tick, drives the flash) and `previous_close` (session, drives % change) | PLAN needs both; the cache only had the first |
| D5 | Dhan via a **thin async httpx client**, not the sync `dhanhq` SDK | Event-loop friendly, testable with `httpx.MockTransport`, ~200 lines |
| D6 | Dhan default is **REST polling** (one batched call per cycle); WebSocket is opt-in | 1 call for ≤1000 tickers fits the 1 req/s Quote limit; WS is unverified without a token |
| D7 | Previous close for Dhan comes from **daily history** (last bar before today, IST), not `ohlc.close` | Explicit by date; `ohlc.close` semantics are undocumented. Fallback to `ohlc.close` only after history failed |
| D8 | **Fail fast** on `DHANHQ_API_KEY` without `DHANHQ_CLIENT_ID`; **degrade** (don't crash) on runtime auth/outage | Never silently simulate when the user thinks they are on real data; never take the app down for an expired token |
| D9 | **Never write 0/None prices**; omit instead | A zero price corrupts portfolio valuation |
| D10 | Trades refuse **stale** prices (default > 120 s) | With real data, a dead feed must not fill orders at an old quote |
| D11 | Dhan universe = **NSE equities in INR**; the default watchlist switches with the source | Dhan has no US quote/history REST; see DHANHQ_API.md §1 |
| D12 | Keep Massive as a lazily imported legacy tier (owner decision pending) | No breakage; drop later by deleting one file |

---

## 2. Architecture

### 2.1 Modules (`backend/app/market/`)

```text
app/market/
├── __init__.py            public exports
├── errors.py          NEW  exception hierarchy -> HTTP statuses
├── calendar.py        NEW  weekday helpers
├── models.py          MOD  PriceUpdate (+previous_close, day_change*), Bar
├── cache.py           MOD  PriceCache (+previous_close carry-forward, set_previous_close, age, latest_timestamp)
├── interface.py       MOD  MarketDataSource (+metadata, health, on-demand API, default EOD)
├── seed_prices.py     MOD  data for US + NSE profiles; symbol validation; derived seed price
├── synthetic_history.py NEW deterministic daily bars for the simulator
├── simulator.py       MOD  GBMSimulator (+rng, shrinkage, group correlation); SimulatorDataSource (+on-demand API)
├── factory.py         MOD  source selection, default_watchlist(), env options
├── service.py         NEW  MarketDataService: lifecycle, priced-set sync, trade pricing, status
├── api.py             NEW  /api/market/* routes + error->HTTP mapping
├── stream.py               SSE endpoint (UNCHANGED)
├── massive_client.py       legacy source (UNCHANGED, lazily imported)
└── dhan/
    ├── hours.py       NEW  NSE session helpers (IST)
    ├── client.py      NEW  async REST client: quotes, history, token helpers, throttle, error mapping
    ├── instruments.py NEW  ticker <-> (segment, security_id) from Dhan's instrument list
    ├── feed.py        NEW  WebSocket packet parser + reconnecting DhanFeed
    └── source.py      NEW  DhanDataSource
```

### 2.2 Data flow

```text
 .env ──► create_market_data_source(cache) ──► SimulatorDataSource │ DhanDataSource │ MassiveDataSource
                                                   │ push                │ push (REST poll and/or WS ticks)
                                                   ▼                     ▼
                       ┌──────────────────────  PriceCache  ──────────────────────┐
                       ▼                            ▼                              ▼
              SSE /api/stream/prices      portfolio valuation            MarketDataService.price_for_trade()
                  (every ~500 ms)           (reads cache)                 (cache → one-off quote fallback)

  MarketDataService (the only thing routes import)
    ├─ start(watchlist, held) / stop()
    ├─ sync(watchlist, held)   ◄── called after every watchlist or position change
    ├─ price_for_trade(t)      ◄── trade route, LLM trades
    ├─ status()                ◄── /api/health
    └─ .source.is_supported / get_quotes / get_daily_bars / get_eod_closes   (on-demand)
```

### 2.3 Priced-set lifecycle (the part PLAN §1 requires)

```text
watchlist = {AAPL, MSFT}   held = {}            streamed = {AAPL, MSFT}
user buys TSLA (not watched)                    sync() → streamed = {AAPL, MSFT, TSLA}
user removes AAPL from watchlist (not held)     sync() → streamed = {MSFT, TSLA}      AAPL leaves the cache
user removes TSLA from watchlist but holds it   sync() → TSLA stays priced
user sells all TSLA                             sync() → TSLA removed
```

---

## 3. Configuration

### 3.1 Environment (`.env.example` additions)

```bash
# --- Market data -------------------------------------------------------------
# Optional: DhanHQ access token (JWT). If set, real NSE data is used (INR) and
# DHANHQ_CLIENT_ID becomes REQUIRED. If empty, the built-in simulator is used.
# Data APIs are a separately chargeable Dhan subscription.
DHANHQ_API_KEY=
DHANHQ_CLIENT_ID=

# Optional Dhan tuning
DHANHQ_POLL_INTERVAL=2.0        # seconds between quote polls (clamped to >= 1.0)
DHANHQ_USE_WEBSOCKET=false      # true = tick-by-tick feed, REST becomes a 30 s reconciliation
DHANHQ_RENEW_TOKEN=false        # true = renew the (web-generated) token every 12 h, in memory only
DHANHQ_CACHE_DIR=/app/db        # where the instrument list is cached (the Docker volume)
# DHANHQ_BASE_URL=              # do NOT set to the sandbox for prices: it has no quote endpoints

# Optional: Massive (legacy US data). Used only when DHANHQ_API_KEY is empty.
MASSIVE_API_KEY=

# Optional: integer seed => the simulator produces the same price paths every run
MARKET_SEED=
```

Precedence (evaluated once at startup): `DHANHQ_API_KEY` → Dhan; else `MASSIVE_API_KEY` → Massive; else simulator.

### 3.2 Dependencies (`backend/pyproject.toml`)

```toml
dependencies = [
    # ... existing ...
    "httpx>=0.27.0",        # Dhan REST client (already a transitive dev dependency of FastAPI's TestClient)
    "websockets>=13.0",     # Dhan live feed (already pulled in by uvicorn[standard])
]
```

`uv add httpx websockets` updates `uv.lock`. Both are imported lazily (only in Dhan mode), so simulator mode loads neither.

### 3.3 Network egress (Docker / hosting)

Dhan mode needs outbound HTTPS to `api.dhan.co` and `s3.ap-south-1.amazonaws.com` (the instrument list redirects to a pre-signed S3 URL), plus `wss://api-feed.dhan.co` when `DHANHQ_USE_WEBSOCKET=true`. Simulator mode needs no network.

---

## 4. Core layer (shared by every source)

### 4.1 `errors.py`: one hierarchy, mapped to HTTP once

Routes never import provider-specific exceptions; they catch `MarketDataError` and call `to_http()` (§10).

```python
# app/market/errors.py
"""Exceptions surfaced by the market data layer.

Routes map these to HTTP statuses without knowing which provider is active:
    CapabilityError      -> 501   (this source cannot do that)
    UnknownTickerError   -> 422   (ticker cannot be priced)
    StalePriceError      -> 503   (data too old to trade on)
    ProviderAuthError    -> 503   (credentials/subscription problem)
    ProviderError        -> 502   (upstream failure)
"""

from __future__ import annotations


class MarketDataError(Exception):
    """Base class for market-data failures."""


class CapabilityError(MarketDataError):
    """The active source cannot do what was asked (e.g. history on a legacy source)."""


class UnknownTickerError(MarketDataError):
    """The ticker cannot be priced by the active source."""


class StalePriceError(MarketDataError):
    """The latest price is older than the caller allows."""


class ProviderError(MarketDataError):
    """An upstream provider call failed."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class ProviderAuthError(ProviderError):
    """Bad/expired credentials or missing data subscription. Not retryable."""
```

### 4.2 `models.py`: `PriceUpdate` and `Bar`

Backward compatible: the new field has a default, and `to_dict()` only gains keys. Missing values are `None`, never `0`.

```python
# app/market/models.py
"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time.

    Two different "previous" values exist on purpose:
      previous_price  the previous *tick*; drives the green/red flash animation
      previous_close  the previous *session's* close; drives "% change" columns
    """

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    previous_close: float | None = None

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float | None:
        """Absolute change vs the previous close, or None when unknown."""
        if self.previous_close is None:
            return None
        return round(self.price - self.previous_close, 4)

    @property
    def day_change_percent(self) -> float | None:
        """Percentage change vs the previous close, or None when unknown."""
        if not self.previous_close:
            return None
        return round((self.price - self.previous_close) / self.previous_close * 100, 4)

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "previous_close": self.previous_close,
            "day_change": self.day_change,
            "day_change_percent": self.day_change_percent,
        }


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV candle. `date` is the exchange-local trading date."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
```

### 4.3 `cache.py`: previous close carried forward

`update()` accepts `previous_close` and carries the last known value forward, so a source supplies it only when it learns or changes it. `set_previous_close()` handles a value that arrives *after* the first tick (a feed packet, or the history lookup finishing).

```python
# app/market/cache.py
"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from dataclasses import replace
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: one MarketDataSource (simulator, Dhan, ...).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        previous_close: float | None = None,
    ) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Direction/change come from the previous *tick*. `previous_close` is carried
        forward from the last entry when the caller does not supply one, so a source
        only has to pass it when it learns or changes it.
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            if previous_close is None and prev is not None:
                previous_close = prev.previous_close

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
                previous_close=None if previous_close is None else round(previous_close, 2),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def set_previous_close(self, ticker: str, previous_close: float) -> PriceUpdate | None:
        """Attach a previous close to an existing entry (e.g. a feed packet that arrives
        after the first tick). No-op returning None if the ticker has no price yet."""
        with self._lock:
            current = self._prices.get(ticker)
            if current is None:
                return None
            updated = replace(current, previous_close=round(previous_close, 2))
            self._prices[ticker] = updated
            self._version += 1
            return updated

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def age(self, ticker: str, now: float | None = None) -> float | None:
        """Seconds since the ticker was last written, or None if absent."""
        update = self.get(ticker)
        if update is None:
            return None
        return (now if now is not None else time.time()) - update.timestamp

    def latest_timestamp(self) -> float | None:
        """Timestamp of the most recent write across all tickers (for health checks)."""
        with self._lock:
            return max((u.timestamp for u in self._prices.values()), default=None)

    def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (e.g., when removed from watchlist)."""
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        """Current version counter. Useful for SSE change detection."""
        return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

> **Gotcha caught by the tests:** `PriceCache` defines `__len__`, so an *empty* cache is falsy. `cache or PriceCache()` silently replaces the caller's cache. Always use `is not None` (see `MarketDataService.__init__`).

### 4.4 `interface.py`: the Unified API

Two access patterns on one ABC:

- **Streaming:** `start / stop / add_ticker / remove_ticker / get_tickers`: the source pushes into the cache.
- **On-demand:** `is_supported / get_quotes / get_daily_bars / get_eod_closes`: request/response; never writes the cache.

`get_eod_closes()` has a working default (fan-out over `get_daily_bars`, take the last close on or before `on`) so each source only implements bars. `latest_completed_session()` lets each market define when "yesterday's close" is final.

```python
# app/market/interface.py
"""Abstract interface for market data sources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

from .calendar import last_weekday_before
from .errors import (  # noqa: F401  (re-exported for callers)
    CapabilityError,
    MarketDataError,
    ProviderError,
    StalePriceError,
    UnknownTickerError,
)
from .models import Bar, PriceUpdate

logger = logging.getLogger(__name__)


class MarketDataSource(ABC):
    """Contract for market data providers.

    Two access patterns:
      streaming  start()/add_ticker()/remove_ticker(): the source pushes PriceUpdates
                 into the shared PriceCache on its own schedule. Consumers read the cache.
      on demand  is_supported()/get_quotes()/get_daily_bars()/get_eod_closes(): request/
                 response calls for validation, snapshots and history. They never write
                 to the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("TSLA"); await source.remove_ticker("GOOGL")
        await source.stop()
    """

    name: str = "unknown"  # "simulator" | "dhanhq" | "massive"
    currency: str = "USD"  # ISO code prices are quoted in

    # ---- streaming lifecycle ------------------------------------------------
    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates. Called exactly once. Tickers the source cannot
        price are skipped (logged), never fatal."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop background work and release resources. Safe to call multiple times."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if present or unsupported."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and from the PriceCache. No-op if absent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the tickers currently being streamed."""

    # ---- health ----------------------------------------------------------------
    @property
    def healthy(self) -> bool:
        """False when the source is known to be failing (bad token, outage)."""
        return True

    # ---- validation (cheap, no network) ---------------------------------------
    async def is_supported(self, ticker: str) -> bool:
        """True if this source can price `ticker`."""
        return True

    # ---- on-demand snapshots ------------------------------------------------------
    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """Latest price for many tickers in one shot. Unsupported tickers are omitted.
        Does not require the tickers to be streaming; does not write to the cache."""
        raise CapabilityError(f"{self.name} does not support get_quotes")

    # ---- end of day -----------------------------------------------------------------
    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Daily OHLCV bars with start <= date <= end, ascending. May be empty."""
        raise CapabilityError(f"{self.name} does not support get_daily_bars")

    def latest_completed_session(self) -> date:
        """Most recent trading date whose daily bar is final."""
        return last_weekday_before(date.today())

    async def get_eod_closes(
        self, tickers: list[str], on: date | None = None
    ) -> dict[str, float]:
        """Close for many tickers on trading date `on` (default: latest completed session;
        if `on` was a non-trading day, the last session before it). Tickers with no data
        are omitted. Default implementation fans out get_daily_bars()."""
        end = on or self.latest_completed_session()
        start = end - timedelta(days=10)  # spans weekends and holidays
        results = await asyncio.gather(
            *(self.get_daily_bars(t, start, end) for t in tickers), return_exceptions=True
        )
        out: dict[str, float] = {}
        for ticker, bars in zip(tickers, results):
            if isinstance(bars, CapabilityError):
                raise bars
            if isinstance(bars, Exception):
                logger.warning("EOD fetch failed for %s: %s", ticker, bars)
            elif bars:
                out[ticker.upper()] = bars[-1].close
        return out
```

`calendar.py` holds the weekday helpers shared by the simulator, the interface default and Dhan:

```python
# app/market/calendar.py
"""Tiny trading-calendar helpers (weekdays only; exchange holidays are not modelled)."""

from __future__ import annotations

from datetime import date, timedelta


def last_weekday_before(d: date) -> date:
    """Most recent weekday strictly before `d`."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def weekdays_ending_at(end: date, n: int) -> list[date]:
    """The n weekday dates ending at `end` (inclusive), ascending."""
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]
```

---

## 5. The Simulator

### 5.1 Approach (summary; maths and rationale in MARKET_SIMULATOR.md)

GBM per tick, `S(t+dt) = S(t)·exp((μ−σ²/2)·dt + σ·√dt·Z)`, with `Z` correlated across tickers via a Cholesky-factored sector correlation matrix, plus rare 2-5% shock events. Changes relative to the existing code:

| Change | Why |
|---|---|
| `rng: np.random.Generator` injected (`MARKET_SEED`) | Reproducible demos/E2E; no global RNG state |
| `dt = update_interval / TRADING_SECONDS_PER_YEAR` in `SimulatorDataSource` | Changing the interval changes sampling, not market speed (the old code ignored `update_interval` for `dt`) |
| Seed price = previous close, passed on every cache write | PLAN §6; `day_change_percent` starts at 0.00 % |
| Correlation groups are data (`in_it`, `in_banks`, …) | NSE profile without code changes |
| Cholesky shrinkage fallback | A rule-built matrix isn't guaranteed positive-definite; never crash the tick loop |
| Stable `derived_seed_price()` for unknown tickers | Same ticker → same price every run (range $50-300, as the existing test requires) |
| `is_valid_symbol()` | The simulator's definition of "supported" |
| Synthetic daily history anchored at the previous close | EOD API with no real past; deterministic |

Public surface of `GBMSimulator` (`step`, `add_ticker`, `remove_ticker`, `get_price`, `get_tickers`, `_pairwise_correlation`, `_cholesky`) is unchanged, which is why all 73 pre-existing tests pass untouched.

### 5.2 `seed_prices.py`: all market knowledge is data

```python
# app/market/seed_prices.py
"""Seed prices and per-ticker parameters for the market simulator.

Everything here is data. Adding a market means adding rows, not code.
"""

from __future__ import annotations

import re
import zlib

# Realistic starting prices. The seed price doubles as the previous close (PLAN §6).
SEED_PRICES: dict[str, float] = {
    # US (default watchlist)
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
    # India / NSE (default watchlist when DHANHQ is active). Illustrative INR prices.
    "RELIANCE": 2900.00,
    "TCS": 3900.00,
    "INFY": 1500.00,
    "HDFCBANK": 1600.00,
    "ICICIBANK": 1100.00,
    "SBIN": 780.00,
    "BHARTIARTL": 1300.00,
    "ITC": 430.00,
    "LT": 3500.00,
    "HINDUNILVR": 2400.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = more price movement)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},  # Low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},  # Low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
    "RELIANCE": {"sigma": 0.24, "mu": 0.10},
    "TCS": {"sigma": 0.21, "mu": 0.10},
    "INFY": {"sigma": 0.24, "mu": 0.10},
    "HDFCBANK": {"sigma": 0.20, "mu": 0.10},
    "ICICIBANK": {"sigma": 0.22, "mu": 0.10},
    "SBIN": {"sigma": 0.28, "mu": 0.10},
    "BHARTIARTL": {"sigma": 0.24, "mu": 0.10},
    "ITC": {"sigma": 0.19, "mu": 0.08},
    "LT": {"sigma": 0.25, "mu": 0.10},
    "HINDUNILVR": {"sigma": 0.17, "mu": 0.07},
}

# Default parameters for tickers not in the list above (dynamically added)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Correlation groups for the simulator's Cholesky decomposition.
# Tickers in the same group have higher intra-group correlation.
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
    "in_it": {"TCS", "INFY"},
    "in_banks": {"HDFCBANK", "ICICIBANK", "SBIN"},
}

# Correlation coefficients
INTRA_TECH_CORR = 0.6  # Tech stocks move together
INTRA_FINANCE_CORR = 0.5  # Finance stocks move together
CROSS_GROUP_CORR = 0.3  # Between sectors / unknown tickers
TSLA_CORR = 0.3  # TSLA does its own thing
GROUP_CORR: dict[str, float] = {
    "tech": INTRA_TECH_CORR,
    "finance": INTRA_FINANCE_CORR,
    "in_it": 0.65,
    "in_banks": 0.6,
}

# What the simulator accepts as a ticker (letters/digits and . & - ; e.g. BRK.B, M&M, PYPL)
_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.&-]{0,14}")


def is_valid_symbol(ticker: str) -> bool:
    """True if `ticker` looks like a plausible exchange symbol."""
    return _TICKER_RE.fullmatch(ticker.upper()) is not None


def derived_seed_price(ticker: str) -> float:
    """Stable pseudo-random price in [50, 300) as a pure function of the symbol, so an
    unlisted ticker has the same seed on every run."""
    return round(50 + (zlib.crc32(ticker.upper().encode()) % 25_000) / 100, 2)


def seed_price(ticker: str) -> float:
    return SEED_PRICES.get(ticker.upper()) or derived_seed_price(ticker)


def ticker_params(ticker: str) -> dict[str, float]:
    return TICKER_PARAMS.get(ticker.upper(), DEFAULT_PARAMS)
```

### 5.3 `synthetic_history.py`: deterministic daily bars

Algorithm: draw daily log-returns with the ticker's μ/σ from an RNG seeded by the symbol; cumulate; **shift so the last close equals the anchor** (the previous close); derive open (small gap), high/low (wicks) and volume. Same arguments → identical bars (stable charts, exact assertions).

```python
# app/market/synthetic_history.py
"""Deterministic synthetic daily bars for the simulator's end-of-day API."""

from __future__ import annotations

import math
import zlib
from datetime import date

import numpy as np

from .calendar import weekdays_ending_at
from .models import Bar

DAYS_PER_YEAR = 252
HISTORY_LOOKBACK_DAYS = 365  # weekdays generated per request; callers slice


def synth_daily_bars(
    ticker: str,
    end: date,
    n: int,
    anchor_price: float,
    *,
    mu: float = 0.05,
    sigma: float = 0.25,
) -> list[Bar]:
    """Daily OHLCV bars for the n weekdays ending at `end`; the last close == anchor_price.

    Deterministic: the RNG is seeded from the ticker, so identical arguments always give
    identical bars (stable charts, exact assertions in tests).
    """
    if n <= 0:
        return []
    rng = np.random.default_rng(zlib.crc32(ticker.upper().encode()))
    sigma_d = sigma / math.sqrt(DAYS_PER_YEAR)
    r = (mu - 0.5 * sigma**2) / DAYS_PER_YEAR + sigma_d * rng.standard_normal(n)
    cum = np.cumsum(r)
    closes = anchor_price * np.exp(cum - cum[-1])  # shift so the final close == anchor
    gaps = np.exp(rng.normal(0.0, 0.25 * sigma_d, n))
    opens = np.concatenate(([closes[0]], closes[:-1])) * gaps
    opens[0] = closes[0]
    wick_hi = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    wick_lo = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    highs = np.maximum(opens, closes) * (1 + wick_hi)
    lows = np.minimum(opens, closes) * (1 - wick_lo)
    base_vol = 500_000 + (zlib.crc32(ticker.upper()[::-1].encode()) % 9_500_000)
    vols = base_vol * np.exp(rng.normal(0.0, 0.3, n)) * (1 + 20 * np.abs(r))
    return [
        Bar(d, round(float(o), 2), round(float(h), 2), round(float(lo), 2), round(float(c), 2), int(v))
        for d, o, h, lo, c, v in zip(weekdays_ending_at(end, n), opens, highs, lows, closes, vols)
    ]
```

### 5.4 `simulator.py`: `GBMSimulator` and `SimulatorDataSource`

```python
# app/market/simulator.py
"""GBM-based market simulator."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .models import Bar, PriceUpdate
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    GROUP_CORR,
    TSLA_CORR,
    is_valid_symbol,
    seed_price,
    ticker_params,
)
from .synthetic_history import HISTORY_LOOKBACK_DAYS, synth_daily_bars

logger = logging.getLogger(__name__)


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
        # Injected so tests/demos can be deterministic (MARKET_SEED).
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
        self._prices[ticker] = seed_price(ticker)
        self._params[ticker] = dict(ticker_params(ticker))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition of the ticker correlation matrix.

        Called whenever tickers are added or removed. O(n^2) but n < 50.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        # Build the correlation matrix
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        # A rule-built matrix is not guaranteed positive-definite; shrink toward
        # independence until it factorises rather than crashing the tick loop.
        for _ in range(10):
            try:
                self._cholesky = np.linalg.cholesky(corr)
                return
            except np.linalg.LinAlgError:
                corr = 0.9 * corr + 0.1 * np.eye(n)
        logger.warning("Correlation matrix not factorisable; using independent moves")
        self._cholesky = None

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Correlation between two tickers from sector grouping.

          - Same group (tech 0.6, finance 0.5, in_it 0.65, in_banks 0.6)
          - TSLA with anything: 0.3 (it does its own thing)
          - Cross-sector / unknown tickers: 0.3
        """
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        for group, members in CORRELATION_GROUPS.items():
            if t1 in members and t2 in members:
                return GROUP_CORR[group]
        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM simulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to the PriceCache. Also answers the
    on-demand API (quotes, validation, synthetic daily bars) so it is a drop-in
    replacement for a real provider.
    """

    name = "simulator"
    currency = "USD"  # cosmetic: the simulator does not convert

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

    # ---- streaming lifecycle -------------------------------------------------
    async def start(self, tickers: list[str]) -> None:
        tickers = [t.upper() for t in tickers if is_valid_symbol(t)]
        self._sim = GBMSimulator(
            tickers=tickers,
            # dt follows the tick interval so changing it changes sampling, not market speed
            dt=self._interval / GBMSimulator.TRADING_SECONDS_PER_YEAR,
            event_probability=self._event_prob,
            rng=np.random.default_rng(self._seed),
        )
        # Seed the cache so SSE has data immediately; the seed price is the previous close
        for ticker in tickers:
            self._seed_ticker(ticker)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers (seed=%s)", len(tickers), self._seed)

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
        ticker = ticker.upper()
        if self._sim and is_valid_symbol(ticker) and ticker not in self._sim.get_tickers():
            self._sim.add_ticker(ticker)
            self._seed_ticker(ticker)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._prev_close.pop(ticker, None)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    # ---- on-demand API ----------------------------------------------------------
    async def is_supported(self, ticker: str) -> bool:
        return is_valid_symbol(ticker)

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        out: dict[str, PriceUpdate] = {}
        for t in (x.upper() for x in tickers):
            live = self._cache.get(t)
            if live is not None:
                out[t] = live  # streaming: the live price
            elif is_valid_symbol(t):
                p = seed_price(t)  # not streaming: seed snapshot
                out[t] = PriceUpdate(t, p, p, previous_close=p)
        return out

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        t = ticker.upper()
        if not is_valid_symbol(t):
            return []
        anchor = self._prev_close.get(t) or seed_price(t)
        params = ticker_params(t)
        # Fixed lookback keeps the series identical across calls; callers slice it.
        bars = synth_daily_bars(
            t,
            self.latest_completed_session(),
            HISTORY_LOOKBACK_DAYS,
            anchor,
            mu=params["mu"],
            sigma=params["sigma"],
        )
        return [b for b in bars if start <= b.date <= end]

    # ---- internals -----------------------------------------------------------------
    def _seed_ticker(self, ticker: str) -> None:
        price = self._sim.get_price(ticker) if self._sim else None
        if price is None:
            return
        self._prev_close[ticker] = price
        self._cache.update(ticker=ticker, price=price, previous_close=price)

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                if self._sim:
                    for ticker, price in self._sim.step().items():
                        self._cache.update(
                            ticker=ticker, price=price, previous_close=self._prev_close.get(ticker)
                        )
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

Example: the simulator answering the whole Unified API.

```python
cache = PriceCache()
src = SimulatorDataSource(cache, seed=42)
await src.start(["AAPL", "TCS"])

cache.get("AAPL").to_dict()
# {'ticker': 'AAPL', 'price': 190.0, 'previous_price': 190.0, 'previous_close': 190.0,
#  'day_change': 0.0, 'day_change_percent': 0.0, 'direction': 'flat', ...}

await src.is_supported("PYPL")                      # True  (well-formed symbol)
await src.is_supported("???")                       # False
await src.get_quotes(["AAPL", "PYPL"])              # AAPL live; PYPL = stable derived seed snapshot
end = src.latest_completed_session()                # last weekday before today
bars = await src.get_daily_bars("AAPL", end - timedelta(days=30), end)
bars[-1].close == cache.get("AAPL").previous_close  # True: history ends where today's session starts
await src.get_eod_closes(["AAPL", "TCS"])           # {'AAPL': 190.0, 'TCS': 3900.0}
```

---

## 6. Dhan: foundations

### 6.1 `dhan/hours.py`: NSE session

Cash session 09:15-15:30 IST, Mon-Fri. Exchange holidays are not modelled (Dhan simply returns the last price). `latest_completed_session()` trusts today's daily candle only after 16:00 IST.

```python
# app/market/dhan/hours.py
"""NSE trading-hours helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime

from ..calendar import last_weekday_before

IST = timezone(timedelta(hours=5, minutes=30))
OPEN = dtime(9, 15)
CLOSE = dtime(15, 30)
DAILY_BAR_FINAL = dtime(16, 0)  # margin after the bell before today's daily candle is trusted


def now_ist() -> datetime:
    return datetime.now(IST)


def market_is_open(now: datetime | None = None) -> bool:
    """NSE cash session: 09:15-15:30 IST, Mon-Fri. Exchange holidays are not modelled."""
    now = (now or now_ist()).astimezone(IST)
    return now.weekday() < 5 and OPEN <= now.time() <= CLOSE


def latest_completed_session(now: datetime | None = None) -> date:
    """Most recent trading date whose daily bar should be final."""
    now = (now or now_ist()).astimezone(IST)
    if now.weekday() < 5 and now.time() >= DAILY_BAR_FINAL:
        return now.date()
    return last_weekday_before(now.date())
```

### 6.2 `dhan/client.py`: async REST client

Responsibilities and rules:

- **Two throttles** matching Dhan's limits: Quote APIs 1 req/s (1.05 s spacing), Data APIs 5 req/s (0.25 s). Shared by all callers via an `asyncio.Lock`.
- **Chunking:** ≤ 1000 ids per quote request (error `804` otherwise).
- **Both error-body shapes** parsed (`{"errorCode": "DH-901"}` for charts/trading; `{"data": {"808": "…"}, "status": "failed"}` for quotes), then mapped: auth/subscription → `DhanAuthError` (also a `ProviderAuthError`), rate limit → `DhanRateLimitedError`, `DH-907` → `DhanNoDataError` (history returns `[]`), anything else → `DhanError` with `.code`/`.status`.
- **History dates:** `toDate` is non-inclusive, so the client sends `end + 1 day` and filters; daily candles are stamped at IST midnight, converted to an IST `date`.
- **Token helpers:** `validate()` (`GET /profile`), `renew_token()` (`GET /RenewToken`; the response body shape is undocumented, so it accepts `accessToken`/`access_token` and fails loudly otherwise), `set_token()`.

```python
# app/market/dhan/client.py
"""Async REST client for DhanHQ v2: quotes, daily history, token helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta

import httpx

from ..errors import ProviderAuthError, ProviderError
from ..models import Bar
from .hours import IST

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dhan.co/v2"


class DhanError(ProviderError): ...


class DhanAuthError(DhanError, ProviderAuthError): ...  # bad/expired token, client id, no Data API plan


class DhanRateLimitedError(DhanError): ...  # HTTP 429 / DH-904 / 805: back off


class DhanNoDataError(DhanError): ...  # DH-907: nothing for these parameters


# Error codes from the official Annexure (DHANHQ_API.md §10)
_AUTH_CODES = {"DH-901", "DH-902", "806", "807", "808", "809", "810"}
_RATE_CODES = {"DH-904", "805"}


def _error_code(r: httpx.Response) -> tuple[str | None, str]:
    """Dhan has two error body shapes:
    trading/charts: {"errorType","errorCode":"DH-901","errorMessage"}
    quote:          {"data": {"808": "message"}, "status": "failed"}
    """
    try:
        body = r.json()
    except ValueError:
        return None, r.text[:200]
    if isinstance(body, dict):
        if body.get("errorCode"):
            return str(body["errorCode"]), str(body.get("errorMessage", ""))
        data = body.get("data")
        if body.get("status") == "failed" and isinstance(data, dict) and data:
            code, msg = next(iter(data.items()))
            return str(code), str(msg)
    return None, r.text[:200]


class _Throttle:
    """Allow at most one call per `min_interval` seconds across concurrent tasks."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = max(now, self._next) + self._min


class DhanClient:
    def __init__(
        self,
        client_id: str,
        access_token: str,
        *,
        base_url: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._http = http or httpx.AsyncClient(
            base_url=base_url or BASE_URL,
            headers={
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(10.0),
        )
        self._quote_gate = _Throttle(1.05)  # Quote APIs: 1 req/s
        self._data_gate = _Throttle(0.25)  # Data APIs: 5 req/s

    async def aclose(self) -> None:
        await self._http.aclose()

    def set_token(self, access_token: str) -> None:
        self._http.headers["access-token"] = access_token

    @property
    def token(self) -> str:
        return self._http.headers["access-token"]

    async def _request(self, method: str, path: str, gate: _Throttle | None = None, **kw):
        if gate is not None:
            await gate.wait()
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:  # network / timeout
            raise DhanError(f"{path}: {e.__class__.__name__}: {e}") from e
        if r.status_code >= 400:
            code, msg = _error_code(r)
            detail = f"{path}: HTTP {r.status_code} {code or ''} {msg}".strip()
            if r.status_code == 429 or code in _RATE_CODES:
                raise DhanRateLimitedError(detail, status=r.status_code, code=code)
            if r.status_code in (401, 403) or code in _AUTH_CODES:
                raise DhanAuthError(detail, status=r.status_code, code=code)
            if code == "DH-907":
                raise DhanNoDataError(detail, status=r.status_code, code=code)
            raise DhanError(detail, status=r.status_code, code=code)
        return r.json()

    # ---- quotes -----------------------------------------------------------------
    async def market_quotes(
        self, securities: dict[str, list[int]], kind: str = "ohlc"
    ) -> dict[str, dict[int, dict]]:
        """kind is 'ltp' | 'ohlc' | 'quote'.
        {segment: [ids]} -> {segment: {security_id(int): {...}}}, <=1000 ids per request."""
        if kind not in {"ltp", "ohlc", "quote"}:
            raise ValueError(f"unknown quote kind {kind!r}")
        out: dict[str, dict[int, dict]] = {}
        for segment, ids in securities.items():
            for i in range(0, len(ids), 1000):
                chunk = ids[i : i + 1000]
                body = await self._request(
                    "POST", f"/marketfeed/{kind}", self._quote_gate, json={segment: chunk}
                )
                for sec_id, q in ((body.get("data") or {}).get(segment) or {}).items():
                    out.setdefault(segment, {})[int(sec_id)] = q
        return out

    async def ohlc(self, securities: dict[str, list[int]]) -> dict[str, dict[int, dict]]:
        return await self.market_quotes(securities, "ohlc")

    # ---- history -----------------------------------------------------------------
    async def daily_bars(
        self, security_id: int, segment: str, start: date, end: date, instrument: str = "EQUITY"
    ) -> list[Bar]:
        """Daily candles with start <= IST date <= end, ascending. DH-907 -> []."""
        try:
            body = await self._request(
                "POST",
                "/charts/historical",
                self._data_gate,
                json={
                    "securityId": str(security_id),
                    "exchangeSegment": segment,
                    "instrument": instrument,
                    "expiryCode": 0,
                    "oi": False,
                    "fromDate": start.isoformat(),
                    "toDate": (end + timedelta(days=1)).isoformat(),  # toDate is non-inclusive
                },
            )
        except DhanNoDataError:
            return []
        bars: list[Bar] = []
        for i, ts in enumerate(body.get("timestamp") or []):
            day = datetime.fromtimestamp(ts, IST).date()  # daily candles are stamped at IST midnight
            if start <= day <= end:
                bars.append(
                    Bar(
                        day,
                        body["open"][i],
                        body["high"][i],
                        body["low"][i],
                        body["close"][i],
                        int(body["volume"][i]),
                    )
                )
        return bars

    # ---- token helpers ---------------------------------------------------------------
    async def validate(self) -> None:
        """GET /profile: raises DhanAuthError if the token/client id are not valid."""
        await self._request(
            "GET", "/profile", headers={"dhanClientId": self._client_id}
        )

    async def renew_token(self) -> str:
        """GET /RenewToken: swaps the current (still-valid, web-generated) token for a new
        24 h one and installs it. The response body shape is not documented; we accept the
        usual key spellings and fail loudly otherwise."""
        body = await self._request("GET", "/RenewToken", headers={"dhanClientId": self._client_id})
        new = (body or {}).get("accessToken") or (body or {}).get("access_token") or (
            (body or {}).get("data") or {}
        ).get("accessToken")
        if not new:
            raise DhanError("RenewToken response did not contain a token")
        self.set_token(new)
        return new
```

### 6.3 `dhan/instruments.py`: ticker ↔ security ID

Loads `GET /v2/instrument/NSE_EQ` (no auth, ~1.6 MB, follows the 302 to S3), keeps `EQUITY` rows of series `EQ` (unique per symbol, verified on the live list), caches to `DHANHQ_CACHE_DIR` for 24 h, **asserts the header** (a format change fails loudly instead of yielding an empty map), and falls back to a stale cached copy if the download fails.

```python
# app/market/dhan/instruments.py
"""Ticker <-> Dhan (segment, security_id) resolution from Dhan's instrument list."""

from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Segment-wise list: no auth, ~1.6 MB, 302-redirects to a pre-signed S3 URL (follow redirects).
# Always the production host, even if DHANHQ_BASE_URL is overridden.
NSE_EQ_URL = "https://api.dhan.co/v2/instrument/NSE_EQ"
_REQUIRED = {"EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "SERIES", "UNDERLYING_SYMBOL"}


@dataclass(frozen=True, slots=True)
class Instrument:
    ticker: str  # exchange symbol, e.g. "TCS" (UNDERLYING_SYMBOL)
    security_id: int
    segment: str  # "NSE_EQ"
    instrument: str  # "EQUITY"
    name: str = ""  # DISPLAY_NAME, e.g. "Tata Consultancy Services"


class InstrumentResolver:
    def __init__(self, cache_dir: Path, max_age_s: float = 86_400, url: str = NSE_EQ_URL) -> None:
        self._path = Path(cache_dir) / "dhan-nse-eq-instruments.csv"
        self._max_age = max_age_s
        self._url = url
        self._by_ticker: dict[str, Instrument] = {}
        self._by_key: dict[tuple[str, int], Instrument] = {}

    def __len__(self) -> int:
        return len(self._by_ticker)

    async def load(self) -> None:
        text = await self._read_or_download()
        reader = csv.DictReader(io.StringIO(text))
        missing = _REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(
                f"Dhan instrument list format changed; missing columns: {sorted(missing)}"
            )
        by_ticker: dict[str, Instrument] = {}
        by_key: dict[tuple[str, int], Instrument] = {}
        for row in reader:
            # The file also holds INDEX rows and non-EQ series (SG, SM, BE, ...).
            # EQUITY + series EQ is unique per symbol.
            if (
                row["EXCH_ID"] == "NSE"
                and row["SEGMENT"] == "E"
                and row["INSTRUMENT"] == "EQUITY"
                and row["SERIES"] == "EQ"
            ):
                inst = Instrument(
                    row["UNDERLYING_SYMBOL"].strip().upper(),
                    int(row["SECURITY_ID"]),
                    "NSE_EQ",
                    "EQUITY",
                    row.get("DISPLAY_NAME", "").strip(),
                )
                by_ticker.setdefault(inst.ticker, inst)
                by_key[(inst.segment, inst.security_id)] = inst
        self._by_ticker, self._by_key = by_ticker, by_key
        logger.info("Dhan instrument list loaded: %d NSE equities", len(by_ticker))

    def resolve(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker.upper())

    def by_key(self, segment: str, security_id: int) -> Instrument | None:
        return self._by_key.get((segment, security_id))

    async def _read_or_download(self) -> str:
        if self._path.exists() and time.time() - self._path.stat().st_mtime < self._max_age:
            return self._path.read_text()
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
                r = await http.get(self._url)
                r.raise_for_status()
        except httpx.HTTPError:
            if self._path.exists():  # stale copy beats nothing
                logger.warning("Dhan instrument download failed; using stale cached copy")
                return self._path.read_text()
            raise
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(r.text)
        except OSError:
            logger.warning("Could not cache Dhan instrument list at %s", self._path)
        return r.text
```

Live result (2026-10-22): 2,732 NSE equities in 3.1 s cold, 0.05 s from the disk cache. IDs for the default NSE watchlist: RELIANCE 2885, TCS 11536, INFY 1594, HDFCBANK 1333, ICICIBANK 4963, SBIN 3045, BHARTIARTL 10604, ITC 1660, LT 11483, HINDUNILVR 1394.

### 6.4 `dhan/feed.py`: WebSocket (opt-in)

- `parse_packet()`: little-endian; handles **Ticker** (code 2) and **Previous Close** (code 6); raises `FeedDisconnectError` for code 50; returns `None` for truncated/unhandled packets (never raises on garbage).
- `DhanFeed`: one connection, subscribes in batches of ≤ 100, **replays all subscriptions after every reconnect**, supports live `subscribe`/`unsubscribe` (unsubscribe = request code + 1).
- **Bad-token behaviour (observed on the real host):** Dhan accepts the connection and then drops it with no close frame and no disconnect packet. So a connection that dies within 10 s *without any data* counts as a failure; after 3 in a row `auth_suspect=True` and the backoff grows from 30 s to 5 min. An explicit server code 806-809 flags it immediately. The token is in the URL: **it is never logged**.

```python
# app/market/dhan/feed.py
"""DhanHQ live market feed (WebSocket): binary packet parser + reconnecting client."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import websockets

logger = logging.getLogger(__name__)

WSS_URL = "wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2"
SEGMENT_NAMES = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}
REQ_TICKER = 15  # subscribe Ticker; unsubscribe is code + 1
DISCONNECT_REASONS = {
    805: "connection limit exceeded",
    806: "Data APIs not subscribed",
    807: "access token expired",
    808: "authentication failed (check client id)",
    809: "access token invalid",
}


@dataclass(frozen=True, slots=True)
class FeedEvent:
    kind: str  # "ltp" | "prev_close"
    segment: str
    security_id: int
    value: float


class FeedDisconnectError(Exception):
    """Server sent a Feed Disconnect packet (response code 50)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"{code}: {DISCONNECT_REASONS.get(code, 'unknown')}")
        self.code = code


def parse_packet(buf: bytes) -> FeedEvent | None:
    """Parse one binary frame (little-endian). Unhandled packet types return None.
    Layouts: DHANHQ_API.md §8.3. Raises FeedDisconnectError for code 50."""
    if len(buf) < 8:
        return None
    code = buf[0]
    if code == 2 and len(buf) >= 16:  # Ticker: LTP f32, LTT i32
        _, _, seg, sec, ltp, _ltt = struct.unpack("<BHBIfI", buf[:16])
        return FeedEvent("ltp", SEGMENT_NAMES.get(seg, str(seg)), sec, round(ltp, 2))
    if code == 6 and len(buf) >= 16:  # Previous close: close f32, prev OI i32
        _, _, seg, sec, prev, _oi = struct.unpack("<BHBIfI", buf[:16])
        return FeedEvent("prev_close", SEGMENT_NAMES.get(seg, str(seg)), sec, round(prev, 2))
    if code == 50 and len(buf) >= 10:
        raise FeedDisconnectError(struct.unpack("<H", buf[8:10])[0])
    return None


class DhanFeed:
    """Keeps one WebSocket connected and subscribed; calls on_event for each tick.

    - Re-subscribes everything after every reconnect.
    - A connection that is accepted and then dropped quickly with no data (what Dhan does
      for a bad token) counts as a failure; after `auth_suspect_after` of them in a row
      `auth_suspect` turns True and the backoff grows from 30 s to 5 min.
    - The token is passed in the URL: never log the URL.
    """

    def __init__(
        self,
        client_id: str,
        token: str | Callable[[], str],
        on_event: Callable[[FeedEvent], None],
        *,
        url_template: str = WSS_URL,
        auth_suspect_after: int = 3,
        quick_fail_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._token = token if callable(token) else (lambda: token)
        self._on_event = on_event
        self._url_template = url_template
        self._suspect_after = auth_suspect_after
        self._quick_fail = quick_fail_seconds
        self._subs: set[tuple[str, int]] = set()
        self._ws = None
        self._task: asyncio.Task | None = None
        self.connected = False
        self.auth_suspect = False
        self.last_disconnect_code: int | None = None

    # ---- public ------------------------------------------------------------------
    async def start(self, instruments: Iterable[tuple[str, int]] = ()) -> None:
        self._subs |= set(instruments)
        self._task = asyncio.create_task(self._run(), name="dhan-feed")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self.connected = False

    async def subscribe(self, items: Iterable[tuple[str, int]]) -> None:
        new = set(items) - self._subs
        self._subs |= new
        await self._send(REQ_TICKER, new)

    async def unsubscribe(self, items: Iterable[tuple[str, int]]) -> None:
        gone = set(items) & self._subs
        self._subs -= gone
        await self._send(REQ_TICKER + 1, gone)

    # ---- internals -----------------------------------------------------------------
    async def _send(self, request_code: int, items: set[tuple[str, int]]) -> None:
        ws = self._ws
        if not items or ws is None:
            return  # not connected: subscriptions are replayed on connect
        ordered = sorted(items)
        try:
            for i in range(0, len(ordered), 100):  # <=100 instruments per message
                batch = ordered[i : i + 100]
                await ws.send(
                    json.dumps(
                        {
                            "RequestCode": request_code,
                            "InstrumentCount": len(batch),
                            "InstrumentList": [
                                {"ExchangeSegment": s, "SecurityId": str(n)} for s, n in batch
                            ],
                        }
                    )
                )
        except websockets.WebSocketException:
            logger.debug("Dhan feed send failed; will resubscribe on reconnect")

    async def _run(self) -> None:
        failures = 0
        while True:
            started = time.monotonic()
            got_data = False
            forced = False  # an explicit auth-type disconnect: skip the fast-retry ladder
            try:
                url = self._url_template.format(token=self._token(), client_id=self._client_id)
                async with websockets.connect(url, open_timeout=15) as ws:
                    self._ws = ws
                    await self._send(REQ_TICKER, set(self._subs))
                    self.connected = True
                    async for msg in ws:
                        if not isinstance(msg, bytes):
                            continue
                        event = parse_packet(msg)
                        if event is not None:
                            got_data = True
                            failures = 0
                            self.auth_suspect = False
                            self._on_event(event)
            except asyncio.CancelledError:
                raise
            except FeedDisconnectError as e:
                self.last_disconnect_code = e.code
                self.auth_suspect = forced = e.code in (806, 807, 808, 809)
                logger.error("Dhan feed disconnected by server: %s", e)
                if forced:
                    failures = self._suspect_after
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                logger.warning("Dhan feed connection ended: %s", e.__class__.__name__)
            finally:
                self._ws = None
                self.connected = False

            if forced:
                pass
            elif not got_data and time.monotonic() - started < self._quick_fail:
                failures += 1
            elif got_data:
                failures = 0
            if failures >= self._suspect_after:
                self.auth_suspect = True
            if failures < self._suspect_after:
                delay = min(2.0**failures, 30.0)
            else:
                delay = min(30.0 * 2 ** (failures - self._suspect_after), 300.0)
            await asyncio.sleep(delay)
```

---

## 7. Dhan: `DhanDataSource`

### 7.1 Behaviour

| Aspect | Design |
|---|---|
| Real-time | One `POST /marketfeed/ohlc` per cycle for **all** priced tickers (grouped by segment); `DHANHQ_POLL_INTERVAL` default 2 s, clamped ≥ 1 s |
| Cadence | Market open and no live feed: every `poll_interval`. Market closed *or* feed connected: every 30 s (reconciliation / health probe) |
| Previous close | Last daily bar dated **before today (IST)**, fetched per ticker in a background task at start, on `add_ticker`, and on IST day rollover. With the WebSocket on, the feed's Previous Close packet wins |
| Fallback | `ohlc.close` is used **only after** the history lookup for that ticker finished without a result, and an immediate re-poll applies it (no 30 s wait) |
| Unsupported tickers | Skipped with a WARNING (e.g. US tickers from an old DB); no cache entry; trades on them are refused |
| Rate limited | Interval doubles up to 30 s, then recovers |
| Auth/subscription error | `healthy=False`, ERROR once, `last_error` set, poll every 60 s; last prices stay in the cache (their timestamps stop advancing → the UI and `price_for_trade` see them as stale) |
| Other errors / crashes | Logged, backoff, loop never dies |
| Startup | Validates the token via `/profile`: a bad token makes the source **unhealthy, not fatal** |
| Optional renewal | `DHANHQ_RENEW_TOKEN=true`: renew every 12 h (works only for web-generated, still-valid tokens; the new token lives in memory) |

### 7.2 Code

```python
# app/market/dhan/source.py
"""DhanHQ market data source: REST polling (default) with an optional WebSocket feed."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from ..cache import PriceCache
from ..interface import MarketDataSource
from ..models import Bar, PriceUpdate
from .client import DhanAuthError, DhanClient, DhanError, DhanRateLimitedError
from .feed import DhanFeed, FeedEvent
from .hours import latest_completed_session, market_is_open, now_ist
from .instruments import Instrument, InstrumentResolver

logger = logging.getLogger(__name__)

CLOSED_POLL_SECONDS = 30.0  # market closed, or feed healthy: REST is only a reconciliation
RENEW_EVERY_SECONDS = 12 * 3600


class DhanDataSource(MarketDataSource):
    name = "dhanhq"
    currency = "INR"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        price_cache: PriceCache,
        cache_dir: Path,
        poll_interval: float = 2.0,
        *,
        base_url: str | None = None,
        use_websocket: bool = False,
        renew_token: bool = False,
        client: DhanClient | None = None,
        resolver: InstrumentResolver | None = None,
        feed: DhanFeed | None = None,
    ) -> None:
        self._cache = price_cache
        self._client_id = client_id
        self._client = client or DhanClient(client_id, access_token, base_url=base_url)
        self._resolver = resolver or InstrumentResolver(cache_dir)
        self._interval = max(1.0, poll_interval)  # Quote API limit: 1 req/s
        self._use_ws = use_websocket
        self._renew = renew_token
        self._feed = feed
        self._tickers: dict[str, Instrument] = {}  # active, resolved tickers
        self._prev_close: dict[str, float] = {}
        self._prev_close_from_feed: set[str] = set()
        self._prev_close_tried: set[str] = set()  # history lookup finished (ok or failed)
        self._prev_close_day: date | None = None
        self._task: asyncio.Task | None = None
        self._bg: set[asyncio.Task] = set()
        self._rest_ok = True
        self._last_error: str | None = None

    # ---- health ---------------------------------------------------------------------
    @property
    def healthy(self) -> bool:
        return self._rest_ok and not (self._feed is not None and self._feed.auth_suspect)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ---- streaming lifecycle ----------------------------------------------------------
    async def start(self, tickers: list[str]) -> None:
        await self._resolver.load()
        try:
            await self._client.validate()
        except DhanAuthError as e:  # do not crash the app: report via health and keep retrying
            self._mark_unhealthy(e)
        except DhanError as e:
            logger.warning("Dhan token validation inconclusive: %s", e)
        for t in tickers:
            self._track(t)
        if self._use_ws:
            self._feed = self._feed or DhanFeed(
                self._client_id, lambda: self._client.token, self._on_feed_event
            )
            await self._feed.start(self._feed_keys(self._tickers.values()))
        # The loop's first iteration sees _prev_close_day is None and kicks off the refresh.
        self._task = asyncio.create_task(self._run_loop(), name="dhan-poll")
        if self._renew:
            self._spawn(self._renew_loop())
        logger.info(
            "Dhan source started: %d/%d tickers resolved, websocket=%s",
            len(self._tickers), len(tickers), self._use_ws,
        )

    async def stop(self) -> None:
        tasks = [t for t in [self._task, *self._bg] if t]
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        if self._feed is not None:
            await self._feed.stop()
        await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        t = ticker.upper()
        if self._track(t):
            if self._feed is not None:
                await self._feed.subscribe(self._feed_keys([self._tickers[t]]))
            self._spawn(self._refresh_prev_close([t]))
            self._spawn(self._poll_once())  # price appears without waiting a full cycle

    async def remove_ticker(self, ticker: str) -> None:
        t = ticker.upper()
        inst = self._tickers.pop(t, None)
        if inst is not None and self._feed is not None:
            await self._feed.unsubscribe(self._feed_keys([inst]))
        self._prev_close.pop(t, None)
        self._prev_close_from_feed.discard(t)
        self._prev_close_tried.discard(t)
        self._cache.remove(t)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # ---- on-demand API ------------------------------------------------------------------
    async def is_supported(self, ticker: str) -> bool:
        return self._resolver.resolve(ticker) is not None

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        insts = {t.upper(): self._resolver.resolve(t) for t in tickers}
        resolved = [i for i in insts.values() if i is not None]
        if not resolved:
            return {}
        raw = await self._client.ohlc(_group(resolved))
        now = time.time()
        out: dict[str, PriceUpdate] = {}
        for t, inst in insts.items():
            q = raw.get(inst.segment, {}).get(inst.security_id) if inst else None
            if q and q.get("last_price"):
                price = round(float(q["last_price"]), 2)
                prev = self._prev_close.get(t)
                if prev is None:  # no history yet: ohlc.close is the best available guess
                    prev = (q.get("ohlc") or {}).get("close") or None
                out[t] = PriceUpdate(t, price, price, now, prev)
        return out

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        inst = self._resolver.resolve(ticker)
        if inst is None:
            return []
        return await self._client.daily_bars(
            inst.security_id, inst.segment, start, end, inst.instrument
        )

    def latest_completed_session(self) -> date:
        return latest_completed_session()

    # ---- internals ------------------------------------------------------------------------
    def _track(self, ticker: str) -> bool:
        t = ticker.upper()
        inst = self._resolver.resolve(t)
        if inst is None:
            logger.warning("Dhan: %s is not a known NSE equity (series EQ); it will have no price", t)
            return False
        if t in self._tickers:
            return False
        self._tickers[t] = inst
        return True

    @staticmethod
    def _feed_keys(insts) -> list[tuple[str, int]]:
        return [(i.segment, i.security_id) for i in insts]

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _mark_unhealthy(self, err: Exception) -> None:
        if self._rest_ok:
            logger.error("Dhan authentication/subscription problem: %s", err)
        self._rest_ok = False
        self._last_error = str(err)

    async def _refresh_prev_close(self, tickers: list[str]) -> None:
        """Previous close = last daily bar dated before today (IST), from history."""
        today = now_ist().date()
        self._prev_close_day = today  # set first so the loop doesn't respawn us
        failed = False
        for t in tickers:
            inst = self._tickers.get(t)
            if inst is None or t in self._prev_close_from_feed:
                continue
            try:
                bars = await self._client.daily_bars(
                    inst.security_id, inst.segment, today - timedelta(days=10), today, inst.instrument
                )
            except DhanError as e:
                logger.warning("Dhan: previous close for %s unavailable: %s", t, e)
                self._prev_close_tried.add(t)
                failed = True
                continue
            prior = [b for b in bars if b.date < today]
            if prior:
                self._prev_close[t] = prior[-1].close
                self._cache.set_previous_close(t, prior[-1].close)
            self._prev_close_tried.add(t)
        if failed:  # apply the ohlc.close fallback now instead of waiting a (slow) poll cycle
            self._spawn(self._poll_once())

    async def _poll_once(self) -> None:
        active = dict(self._tickers)
        if not active:
            return
        raw = await self._client.ohlc(_group(list(active.values())))
        self._rest_ok = True
        self._last_error = None
        for t, inst in active.items():
            q = raw.get(inst.segment, {}).get(inst.security_id)
            if not q or not q.get("last_price"):
                continue  # keep last cached price; never write 0
            prev = self._prev_close.get(t)
            if prev is None and t in self._prev_close_tried:  # history failed: use ohlc.close
                prev = (q.get("ohlc") or {}).get("close") or None
            self._cache.update(t, float(q["last_price"]), previous_close=prev)

    def _on_feed_event(self, ev: FeedEvent) -> None:
        inst = self._resolver.by_key(ev.segment, ev.security_id)
        if inst is None or inst.ticker not in self._tickers:
            return
        t = inst.ticker
        if ev.kind == "ltp":
            if ev.value > 0:
                self._cache.update(t, ev.value, previous_close=self._prev_close.get(t))
        elif ev.kind == "prev_close":
            self._prev_close[t] = ev.value
            self._prev_close_from_feed.add(t)
            self._prev_close_tried.add(t)
            self._cache.set_previous_close(t, ev.value)

    async def _run_loop(self) -> None:
        delay = self._interval
        while True:
            try:
                if now_ist().date() != self._prev_close_day:  # first run / day rollover
                    self._spawn(self._refresh_prev_close(list(self._tickers)))
                await self._poll_once()
                feed_live = self._feed is not None and self._feed.connected
                delay = self._interval if market_is_open() and not feed_live else CLOSED_POLL_SECONDS
            except asyncio.CancelledError:
                raise
            except DhanRateLimitedError:
                delay = min(delay * 2, 30.0)
                logger.warning("Dhan rate limited; next poll in %.0fs", delay)
            except DhanAuthError as e:
                self._mark_unhealthy(e)
                delay = 60.0
            except DhanError as e:
                self._last_error = str(e)
                logger.warning("Dhan poll failed: %s", e)
                delay = min(max(delay, self._interval) * 2, 30.0)
            except Exception:
                logger.exception("Dhan poll crashed")
                delay = min(max(delay, self._interval) * 2, 30.0)
            await asyncio.sleep(delay)

    async def _renew_loop(self) -> None:
        """Optional: renew the (web-generated) token every 12 h. The new token lives in
        memory only; after a restart the env token is used again."""
        while True:
            await asyncio.sleep(RENEW_EVERY_SECONDS)
            try:
                await self._client.renew_token()
                self._rest_ok = True
                logger.info("Dhan access token renewed")
            except DhanError as e:
                logger.error("Dhan token renewal failed: %s", e)


def _group(insts: list[Instrument]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for i in insts:
        grouped.setdefault(i.segment, []).append(i.security_id)
    return grouped
```

### 7.3 Request budget

| Call | Frequency | Limit | Headroom |
|---|---|---|---|
| `/marketfeed/ohlc` (all tickers, 1 call) | every 2 s (open), 30 s (closed) | 1/s | 50 % at default |
| `/charts/historical` (previous close) | N at start, N at each IST day rollover, 1 per `add_ticker` | 5/s, 100 000/day | 10 tickers ≈ 2 s of throttled calls |
| `/profile` | once at start | – | – |
| EOD for N tickers | N calls, serialized by the 0.25 s throttle | 5/s | 100 tickers ≈ 25 s |

### 7.4 Examples

```python
src = DhanDataSource("1000000001", token, cache, cache_dir=Path("/app/db"))
await src.start(["TCS", "RELIANCE", "NOPE"])        # NOPE: warning, skipped
await src.is_supported("tcs")                       # True
quotes = await src.get_quotes(["TCS", "INFY"])      # one HTTP call; {'TCS': PriceUpdate(...), ...}
end = src.latest_completed_session()                # today after 16:00 IST, else last weekday
bars = await src.get_daily_bars("TCS", end - timedelta(days=30), end)
closes = await src.get_eod_closes(["TCS", "INFY", "RELIANCE"])
# {'TCS': 3912.4, 'INFY': 1494.1, 'RELIANCE': 2907.0}   (N history calls under the 5/s throttle)
```

### 7.5 WebSocket mode in one picture

```text
DHANHQ_USE_WEBSOCKET=true
  start():  resolver.load → validate → feed.start([(NSE_EQ, 11536), ...])        (prev close + ticks arrive)
  feed ─ ltp ─────────► _on_feed_event → cache.update(t, price, previous_close=_prev_close[t])
       ─ prev_close ──► _on_feed_event → _prev_close[t]=v; cache.set_previous_close(t, v)   (wins over history)
  REST loop keeps running every 30 s as reconciliation; if the feed is down it falls back to `poll_interval`
  add_ticker/remove_ticker → feed.subscribe/unsubscribe     healthy = rest_ok AND NOT feed.auth_suspect
```

### 7.6 Why previous close is safe whatever the unverified API details turn out to be

| Unverified question | Effect on the design |
|---|---|
| Does `toDate=tomorrow` include today's partial candle? | Filtered by `bar.date < today`; included or not, previous close is the same |
| What does `ohlc.close` mean during the session? | Not used unless history failed; with the feed on, the Previous Close packet is authoritative |
| Does a holiday/empty range give `DH-907` or empty arrays? | Both → empty list → no previous close → `day_change_percent` is `null`, UI shows `—` |
| Is `/quote`'s `net_change` populated for `NSE_EQ`? | Optional cheaper path (`previous_close = last_price − net_change`, no history calls); evaluate in the smoke test, swap `_refresh_prev_close` if it holds |

---

## 8. Factory and default watchlist

`create_market_data_source(cache)` returns an **unstarted** source; `default_watchlist()` gives the DB seeder the right ten tickers for the active market.

```python
# app/market/factory.py
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

US_DEFAULTS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
NSE_DEFAULTS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "LT", "HINDUNILVR",
]  # fmt: skip


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def dhan_credentials() -> tuple[str, str] | None:
    """(client_id, access_token) when Dhan is selected, else None.

    DHANHQ_API_KEY is the access token. Dhan also needs the client id, so a key
    without it is a configuration error: fail fast instead of silently simulating.
    """
    token = os.environ.get("DHANHQ_API_KEY", "").strip()
    if not token:
        return None
    client_id = os.environ.get("DHANHQ_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "DHANHQ_API_KEY is set but DHANHQ_CLIENT_ID is missing; Dhan requires both. "
            "Unset DHANHQ_API_KEY to use the simulator."
        )
    return client_id, token


def default_watchlist() -> list[str]:
    """Seed watchlist for a fresh database; depends on the active source's market."""
    return list(NSE_DEFAULTS if dhan_credentials() else US_DEFAULTS)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - DHANHQ_API_KEY (+ DHANHQ_CLIENT_ID) set -> DhanDataSource (real NSE data, INR)
    - else MASSIVE_API_KEY set                -> MassiveDataSource (legacy, US data)
    - otherwise                               -> SimulatorDataSource (GBM)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    creds = dhan_credentials()
    if creds:
        from .dhan.source import DhanDataSource  # lazy: no httpx/websockets cost in sim mode

        client_id, token = creds
        base_url = os.environ.get("DHANHQ_BASE_URL", "").strip() or None
        if base_url and "sandbox" in base_url:
            logger.warning(
                "DHANHQ_BASE_URL is the Dhan sandbox, which has no /marketfeed/* quote "
                "endpoints: live prices will not work (history/auth only)"
            )
        logger.info("Market data source: DhanHQ (real data, INR)")
        return DhanDataSource(
            client_id,
            token,
            price_cache,
            cache_dir=Path(os.environ.get("DHANHQ_CACHE_DIR", "/app/db")),
            poll_interval=float(os.environ.get("DHANHQ_POLL_INTERVAL", "2.0")),
            base_url=base_url,
            use_websocket=_flag("DHANHQ_USE_WEBSOCKET"),
            renew_token=_flag("DHANHQ_RENEW_TOKEN"),
        )

    massive_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if massive_key:
        from .massive_client import MassiveDataSource  # lazy: legacy dependency

        logger.info("Market data source: Massive API (legacy)")
        return MassiveDataSource(api_key=massive_key, price_cache=price_cache)

    from .simulator import SimulatorDataSource

    seed = os.environ.get("MARKET_SEED", "").strip()
    logger.info("Market data source: GBM Simulator")
    return SimulatorDataSource(price_cache=price_cache, seed=int(seed) if seed else None)
```

---

## 9. `MarketDataService`: what the rest of the backend uses

Bundles the cache and the source, owns the priced-set reconciliation (§2.3), prices trades, and reports health.

- `start(watchlist, held)` / `stop()`: lifecycle; the union is passed to the source.
- `sync(watchlist, held)`: idempotent diff against `source.get_tickers()`; returns `SyncResult(added, removed, unsupported)`.
- `price_for_trade(ticker, max_age=120)`: cache first, **refuses stale prices** (`StalePriceError`), falls back to a one-off quote for non-streamed tickers, raises `UnknownTickerError` / `MarketDataError`; never returns 0/None.
- `status()`: `{"source", "currency", "healthy", "last_error", "tickers", "last_tick_age_s"}`.

```python
# app/market/service.py
"""MarketDataService: the one object the rest of the backend talks to."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from .cache import PriceCache
from .errors import MarketDataError, StalePriceError, UnknownTickerError
from .factory import create_market_data_source
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

DEFAULT_MAX_PRICE_AGE = 120.0  # seconds; older prices are refused for trading


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)  # wanted but the source cannot price them


def _norm(tickers: Iterable[str]) -> list[str]:
    return sorted({t.strip().upper() for t in tickers if t and t.strip()})


class MarketDataService:
    """Owns the PriceCache + the active MarketDataSource and keeps the *priced set* right.

    Priced tickers = watchlist tickers + held tickers (PLAN §1). Only those receive live
    prices. The DB layer calls `sync()` after any watchlist or position change.
    """

    def __init__(
        self, cache: PriceCache | None = None, source: MarketDataSource | None = None
    ) -> None:
        # NB: `cache or PriceCache()` would be a bug: PriceCache has __len__, so an empty
        # cache is falsy and would be silently replaced.
        self.cache = cache if cache is not None else PriceCache()
        self.source = source if source is not None else create_market_data_source(self.cache)
        self._desired: list[str] = []

    # ---- lifecycle ---------------------------------------------------------------------
    async def start(self, watchlist: Iterable[str], held: Iterable[str] = ()) -> None:
        self._desired = _norm([*watchlist, *held])
        await self.source.start(self._desired)

    async def stop(self) -> None:
        await self.source.stop()

    # ---- priced-set reconciliation ----------------------------------------------------------
    def priced_tickers(self) -> list[str]:
        return sorted(self.source.get_tickers())

    async def sync(self, watchlist: Iterable[str], held: Iterable[str] = ()) -> SyncResult:
        """Make the streamed set equal watchlist ∪ held. Idempotent; cheap when unchanged."""
        want = _norm([*watchlist, *held])
        have = set(self.source.get_tickers())
        result = SyncResult()
        for t in want:
            if t in have:
                continue
            if not await self.source.is_supported(t):
                result.unsupported.append(t)
                continue
            await self.source.add_ticker(t)
            result.added.append(t)
        for t in sorted(have - set(want)):
            await self.source.remove_ticker(t)
            result.removed.append(t)
        self._desired = want
        if result.added or result.removed or result.unsupported:
            logger.info("Market sync: +%s -%s unsupported=%s",
                        result.added, result.removed, result.unsupported)
        return result

    # ---- pricing -----------------------------------------------------------------------------
    def get_price(self, ticker: str) -> float | None:
        return self.cache.get_price(ticker.upper())

    async def price_for_trade(self, ticker: str, max_age: float = DEFAULT_MAX_PRICE_AGE) -> float:
        """Price to fill a market order at. Cache first, one-off quote as a fallback.

        Raises UnknownTickerError (cannot be priced), StalePriceError (feed down), or
        MarketDataError (provider has no price right now). Never returns 0 or None.
        """
        t = ticker.strip().upper()
        update = self.cache.get(t)
        if update is not None:
            age = time.time() - update.timestamp
            if age > max_age:
                raise StalePriceError(f"{t} price is {age:.0f}s old (limit {max_age:.0f}s)")
            return update.price
        if not await self.source.is_supported(t):
            raise UnknownTickerError(f"{t} is not supported by the {self.source.name} source")
        quotes = await self.source.get_quotes([t])
        if t not in quotes:
            raise MarketDataError(f"No price available for {t} right now")
        return quotes[t].price

    # ---- status ------------------------------------------------------------------------------------
    def status(self) -> dict:
        latest = self.cache.latest_timestamp()
        return {
            "source": self.source.name,
            "currency": self.source.currency,
            "healthy": self.source.healthy,
            "last_error": getattr(self.source, "last_error", None),
            "tickers": len(self.source.get_tickers()),
            "last_tick_age_s": None if latest is None else round(time.time() - latest, 1),
        }
```

---

## 10. HTTP surface

### 10.1 Routes (`api.py`)

SSE (`GET /api/stream/prices`, `stream.py`) is **unchanged**. These on-demand routes are **additions to PLAN §8** (propose adding them there); `to_http()` is also what the trade and watchlist routes should use.

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/api/market/status` | Source, currency, health, last tick age | Also embed in `/api/health` |
| GET | `/api/market/supported/{ticker}` | Validate before adding to the watchlist | |
| GET | `/api/market/quotes?tickers=A,B` | One-shot snapshot (≤ 200 tickers) | |
| GET | `/api/market/history/{ticker}?start=&end=` | Daily bars | `end` defaults to the latest completed session |
| GET | `/api/market/eod?tickers=A,B&on=` | Close per ticker | |

Error mapping: `CapabilityError` → 501, `UnknownTickerError` → 422, `StalePriceError` / `ProviderAuthError` → 503, other `ProviderError` → 502.

```python
# app/market/api.py
"""HTTP routes for on-demand market data (validation, quotes, history, EOD).

Streaming stays in stream.py (SSE). These routes are *additions* to PLAN §8.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .errors import (
    CapabilityError,
    MarketDataError,
    ProviderAuthError,
    ProviderError,
    StalePriceError,
    UnknownTickerError,
)
from .service import MarketDataService


def to_http(exc: MarketDataError) -> HTTPException:
    """Map market-data errors to HTTP statuses (usable from any route, e.g. trades)."""
    if isinstance(exc, CapabilityError):
        return HTTPException(501, str(exc))
    if isinstance(exc, UnknownTickerError):
        return HTTPException(422, str(exc))
    if isinstance(exc, (StalePriceError, ProviderAuthError)):
        return HTTPException(503, str(exc))
    if isinstance(exc, ProviderError):
        return HTTPException(502, str(exc))
    return HTTPException(500, str(exc))


def _split(tickers: str) -> list[str]:
    out = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not out:
        raise HTTPException(422, "tickers must be a non-empty comma-separated list")
    if len(out) > 200:
        raise HTTPException(422, "at most 200 tickers per request")
    return out


def create_market_router(service: MarketDataService) -> APIRouter:
    router = APIRouter(prefix="/api/market", tags=["market"])

    @router.get("/status")
    async def status() -> dict:
        return service.status()

    @router.get("/supported/{ticker}")
    async def supported(ticker: str) -> dict:
        t = ticker.strip().upper()
        return {"ticker": t, "supported": await service.source.is_supported(t)}

    @router.get("/quotes")
    async def quotes(tickers: str = Query(..., description="comma-separated")) -> dict:
        try:
            result = await service.source.get_quotes(_split(tickers))
        except MarketDataError as e:
            raise to_http(e) from e
        return {"currency": service.source.currency,
                "quotes": {t: q.to_dict() for t, q in result.items()}}

    @router.get("/history/{ticker}")
    async def history(ticker: str, start: date, end: date | None = None) -> dict:
        t = ticker.strip().upper()
        end = end or service.source.latest_completed_session()
        if start > end:
            raise HTTPException(422, "start must be on or before end")
        if not await service.source.is_supported(t):
            raise HTTPException(422, f"Unsupported ticker: {t}")
        try:
            bars = await service.source.get_daily_bars(t, start, end)
        except MarketDataError as e:
            raise to_http(e) from e
        return {"ticker": t, "currency": service.source.currency,
                "bars": [b.to_dict() for b in bars]}

    @router.get("/eod")
    async def eod(tickers: str = Query(...), on: date | None = None) -> dict:
        try:
            closes = await service.source.get_eod_closes(_split(tickers), on)
        except MarketDataError as e:
            raise to_http(e) from e
        return {"currency": service.source.currency,
                "date": (on or service.source.latest_completed_session()).isoformat(),
                "closes": closes}

    return router
```

```python
# app/market/__init__.py
"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate, Bar            - immutable data models
    PriceCache                  - thread-safe latest-price store
    MarketDataSource            - abstract interface (simulator, DhanHQ, legacy Massive)
    create_market_data_source   - factory that selects the source from the environment
    default_watchlist           - seed watchlist for the active market
    MarketDataService           - lifecycle + priced-set sync + trade pricing + status
    create_stream_router        - SSE endpoint  (GET /api/stream/prices)
    create_market_router        - on-demand endpoints (/api/market/...)
"""

from .api import create_market_router, to_http
from .cache import PriceCache
from .errors import (
    CapabilityError,
    MarketDataError,
    ProviderAuthError,
    ProviderError,
    StalePriceError,
    UnknownTickerError,
)
from .factory import create_market_data_source, default_watchlist
from .interface import MarketDataSource
from .models import Bar, PriceUpdate
from .service import MarketDataService
from .stream import create_stream_router

__all__ = [
    "Bar",
    "CapabilityError",
    "MarketDataError",
    "MarketDataService",
    "MarketDataSource",
    "PriceCache",
    "PriceUpdate",
    "ProviderAuthError",
    "ProviderError",
    "StalePriceError",
    "UnknownTickerError",
    "create_market_data_source",
    "create_market_router",
    "create_stream_router",
    "default_watchlist",
    "to_http",
]
```

### 10.2 Wiring example (lifespan, watchlist, trade)

How the future `main.py` / route modules use the layer. The in-memory `WATCHLIST`/`POSITIONS` stand in for the SQLite layer; in the real app they are DB reads, and **every watchlist or position write is followed by `service.sync(...)`**.

```python
# app/main_example.py
"""Example wiring of the market data layer into the FastAPI app (lifespan + routers)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.market import (
    MarketDataError,
    MarketDataService,
    create_market_router,
    create_stream_router,
    default_watchlist,
    to_http,
)

logging.basicConfig(level=logging.INFO)

# Stand-ins for the DB layer (backend/db): the real app reads these from SQLite.
WATCHLIST: list[str] = []
POSITIONS: dict[str, float] = {}

service = MarketDataService()  # builds the PriceCache + the source chosen by the environment


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not WATCHLIST:  # fresh database: seed with the active market's defaults
        WATCHLIST.extend(default_watchlist())
    await service.start(WATCHLIST, held=POSITIONS)
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(service.cache))  # GET /api/stream/prices (SSE)
app.include_router(create_market_router(service))  # /api/market/...


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok" if service.source.healthy else "degraded", "market": service.status()}


class TickerBody(BaseModel):
    ticker: str


@app.post("/api/watchlist", status_code=201)
async def add_watch(body: TickerBody) -> dict:
    t = body.ticker.strip().upper()
    if t in WATCHLIST:
        raise HTTPException(409, f"{t} is already on the watchlist")
    if not await service.source.is_supported(t):
        raise HTTPException(422, f"Unsupported ticker: {t}")
    WATCHLIST.append(t)
    await service.sync(WATCHLIST, held=POSITIONS)
    return {"ticker": t}


@app.delete("/api/watchlist/{ticker}")
async def remove_watch(ticker: str) -> dict:
    t = ticker.strip().upper()
    if t not in WATCHLIST:
        raise HTTPException(404, f"{t} is not on the watchlist")
    WATCHLIST.remove(t)
    await service.sync(WATCHLIST, held=POSITIONS)  # stays priced if still held
    return {"ticker": t}


class TradeBody(BaseModel):
    ticker: str
    quantity: float
    side: str


@app.post("/api/portfolio/trade")
async def trade(body: TradeBody) -> dict:
    t = body.ticker.strip().upper()
    try:
        price = await service.price_for_trade(t)  # cache -> one-off quote; never 0/None
    except MarketDataError as e:
        raise to_http(e) from e
    sign = 1 if body.side == "buy" else -1
    POSITIONS[t] = POSITIONS.get(t, 0.0) + sign * body.quantity
    if POSITIONS[t] <= 0:
        del POSITIONS[t]
    await service.sync(WATCHLIST, held=POSITIONS)  # a held ticker must be priced
    return {"ticker": t, "price": price, "currency": service.source.currency}
```

### 10.3 Captured output from a running server (simulator, `MARKET_SEED=7`)

```text
GET /api/health
{"status":"ok","market":{"source":"simulator","currency":"USD","healthy":true,"last_error":null,"tickers":10,"last_tick_age_s":0.5}}

GET /api/stream/prices            (first event, one ticker shown)
data: {"AAPL": {"ticker": "AAPL", "price": 189.99, "previous_price": 189.97, "timestamp": 1792664610.48,
        "change": 0.02, "change_percent": 0.0105, "direction": "up", "previous_close": 190.0,
        "day_change": -0.01, "day_change_percent": -0.0053}, "AMZN": {...}, ...}

POST /api/watchlist {"ticker":"pypl"}     → 201 {"ticker":"PYPL"}
POST /api/watchlist {"ticker":"???"}      → 422 {"detail":"Unsupported ticker: ???"}
POST /api/portfolio/trade {"ticker":"PYPL","quantity":5,"side":"buy"}
                                          → {"ticker":"PYPL","price":179.9,"currency":"USD"}
DELETE /api/watchlist/PYPL                → {"ticker":"PYPL"}
GET /api/market/status                    → "tickers": 11     (PYPL is still priced: it is held)

GET /api/market/history/AAPL?start=2026-10-15&end=2026-10-21
{"ticker":"AAPL","currency":"USD","bars":[{"date":"2026-10-15","open":179.45,"high":185.6,"low":179.18,"close":182.94,"volume":8793347}, ...]}

GET /api/market/eod?tickers=AAPL,MSFT     → {"currency":"USD","date":"2026-10-21","closes":{"AAPL":190.0,"MSFT":420.0}}
```

### 10.4 Frontend / LLM contract

| Field (SSE / REST) | UI use |
|---|---|
| `price`, `direction` | Price cell and the green/red **flash** (tick-to-tick) |
| `day_change_percent` (nullable) | Watchlist and positions **% change** column; `null` → `—` |
| `timestamp` | Mark a price **stale** (greyed) when `now − timestamp > 15 s` while the SSE dot stays green |
| `currency` (from `/api/market/status`) | `$` vs `₹`; include in the LLM portfolio context so the assistant doesn't say dollars about INR stocks |
| `healthy: false` | Header badge "market data degraded" |

---

## 11. Operational behaviour

### 11.1 Failure matrix

| Situation | Behaviour | Visible as |
|---|---|---|
| `DHANHQ_API_KEY` without `DHANHQ_CLIENT_ID` | Startup `RuntimeError` with the fix | Container exits with a clear log |
| Token invalid/expired at startup | Source starts **unhealthy**; retries every 60 s | `/api/health` `degraded`, `last_error` |
| Token expires mid-run | Same; cached prices go stale | Stale greying; `price_for_trade` → 503 after 120 s |
| No Data API subscription (`DH-902`/`806`) | Same as auth error | `last_error` |
| 429 / `DH-904` / `805` | Interval doubles to ≤ 30 s, recovers | Log warning |
| Dhan 5xx / network | Backoff ≤ 30 s, keep last prices | Log warning, `last_error` |
| Ticker unknown to Dhan | Skipped, no price, trades refused (422) | Log warning, `—` in UI |
| Market closed / weekend | Poll every 30 s; flat prices; `day_change_percent` still vs the last session | `last_tick_age_s` stays small (the poll refreshes timestamps) |
| Feed drops with no data (bad token) | Backoff 1→30 s, then 30 s→5 min; `auth_suspect` → unhealthy | `/api/health` |
| Instrument download fails, stale copy exists | Uses it with a warning | Log |
| Instrument download fails, no copy | Startup error (nothing can be resolved) | Container exits |
| History lookup fails for a ticker | `ohlc.close` fallback + immediate re-poll | Log warning |
| Simulator step raises | Logged, loop continues | Log |

### 11.2 Token runbook (Dhan tokens last 24 h)

1. Generate at web.dhan.co → My Profile → Access DhanHQ APIs; put in `.env` as `DHANHQ_API_KEY`, set `DHANHQ_CLIENT_ID`.
2. Restart the container to apply a new token (`scripts/start_*.sh`). `/api/health` shows `degraded` + `last_error` when it expires.
3. Optional: `DHANHQ_RENEW_TOKEN=true` renews every 12 h in memory; after a restart the `.env` token is used again, so it must still be valid.
4. Unattended operation would need the TOTP login flow (PIN + TOTP secret); deliberately **not** implemented.

---

## 12. Testing

### 12.1 Layout (227 tests: 73 pre-existing + 154 new)

| File | Tests | Covers |
|---|---|---|
| `test_cache.py`, `test_models.py`, `test_simulator.py`, `test_simulator_source.py`, `test_factory.py`, `test_massive.py` | 73 | Pre-existing, **unmodified and passing** |
| `test_models_cache_v2.py` | 9 | `day_change*`, `None` not `0`, carry-forward, `set_previous_close`, `age`, `latest_timestamp`, `to_dict` back-compat |
| `test_simulator_v2.py` | 27 | Seed determinism, event probability extremes, **correlation ≈ 0.6**, non-PSD shrinkage (mutation-checked), NSE profile, derived price, symbol validation, synthetic history invariants, previous close = seed, `dt` follows interval, quotes/history/EOD, Saturday → Friday |
| `test_dhan_client.py` | 21 | Request shapes, 1000-id chunking, `toDate+1`, IST dates, **both error shapes × 10 codes**, `DH-907 → []`, network errors, throttle spacing, validate/renew |
| `test_dhan_instruments_hours.py` | 15 | Filtering (series, INDEX, BSE), header assertion, **redirect + cache**, stale copy fallback, session open/close boundaries, completed-session logic, UTC input |
| `test_dhan_source.py` | 16 | Prices + previous close, today's partial candle ignored, never 0/missing, history-failure fallback, add/remove, stop, bad token → unhealthy not fatal, recovery, 429/500 survival, token renewal, quotes/bars/EOD, poll cadence open vs closed, interval clamp |
| `test_dhan_feed.py` | 18 | Packet parser (ticker, prev close, rounding, segments, disconnect, truncated), **real local WebSocket server**: subscribe/replay/incremental/unsubscribe, 100-batches, reconnect resubscribe, 807 → auth + backoff, silent drops → auth_suspect, refused connection; source + feed integration |
| `test_factory_v2.py` | 12 | Precedence matrix, fail-fast, env options, sandbox warning, `MARKET_SEED`, default watchlist |
| `test_service_api.py` | 17 | Union/sync/idempotence, held stays priced, `price_for_trade` (stale/unknown), status, HTTP mapping, all routes via `TestClient`, SSE payload |
| `test_contract.py` | 19 | **One suite, both sources** (§12.3) |

Run: `cd backend && uv run --extra dev pytest -v` · lint: `uv run --extra dev ruff check app tests` · coverage: `--cov=app.market`.

### 12.2 Test doubles

No test needs a Dhan account, the network or the wall clock. `FakeDhan` is a stateful `httpx.MockTransport` that answers like the real API (valid candles, quote shape, errors); a fixture pins market hours to "open" so cadence tests don't depend on the time of day (one of the first runs failed after 15:30 IST for exactly that reason).

```python
# tests/market/dhan_fakes.py
"""Shared fakes for Dhan tests: a mock transport that behaves like the real API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx

from app.market.dhan.client import DhanClient
from app.market.dhan.hours import IST, now_ist

INSTRUMENT_CSV = (
    "EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,SERIES\n"
    "NSE,E,11536,X,EQUITY,TCS,TATA CONSULTANCY SERV LT,Tata Consultancy Services,EQ\n"
    "NSE,E,2885,X,EQUITY,RELIANCE,RELIANCE INDUSTRIES LTD,Reliance Industries,EQ\n"
    "NSE,E,1594,X,EQUITY,INFY,INFOSYS LIMITED,Infosys,EQ\n"
    "NSE,E,1000,X,EQUITY,656MH32,SDL MH 6.56% 2032,SDL MH 6.56% 2032,SG\n"
    "NSE,I,13,X,INDEX,NIFTY,NIFTY 50,Nifty,NA\n"
    "BSE,E,500325,X,EQUITY,RELIANCE,RELIANCE,Reliance,A\n"
)
PRICES = {11536: 3950.0, 2885: 2910.5, 1594: 1490.0}
PREV = {11536: 3900.0, 2885: 2900.0, 1594: 1500.0}


def epoch_ist_midnight(d) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=IST).timestamp())


class FakeDhan:
    """Records requests and answers like Dhan. Mutate `.prices`, `.fail` etc. per test."""

    def __init__(self) -> None:
        self.prices = dict(PRICES)
        self.calls: list[tuple[str, str, dict]] = []
        self.fail: tuple[int, dict] | None = None  # (status, body) for every call
        self.history_fail: tuple[int, dict] | None = None
        self.quote_fail: tuple[int, dict] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        assert request.headers["access-token"], "token header missing"
        assert request.headers["client-id"] == "1000000001"
        if self.fail:
            return httpx.Response(self.fail[0], json=self.fail[1])
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"dhanClientId": "1000000001"})
        if path.endswith("/RenewToken"):
            return httpx.Response(200, json={"accessToken": "new-token"})
        if "/marketfeed/" in path:
            if self.quote_fail:
                return httpx.Response(self.quote_fail[0], json=self.quote_fail[1])
            (segment, ids), = body.items()
            data = {
                str(i): {"last_price": self.prices[i],
                         "ohlc": {"open": 1, "close": PREV.get(i, 1.0) - 5, "high": 2, "low": 1}}
                for i in ids if i in self.prices
            }
            return httpx.Response(200, json={"status": "success", "data": {segment: data}})
        if path.endswith("/charts/historical"):
            if self.history_fail:
                return httpx.Response(self.history_fail[0], json=self.history_fail[1])
            sec = int(body["securityId"])
            end = datetime.fromisoformat(body["toDate"]).date() - timedelta(days=1)
            days = [end - timedelta(days=k) for k in range(4, -1, -1)]
            today = now_ist().date()
            ts, close = [], []
            for d in days:
                if d.weekday() < 5 and d <= today:
                    ts.append(epoch_ist_midnight(d))
                    # yesterday-or-earlier closes ascend; the last (today's partial) differs
                    close.append(PREV[sec] if d < today else PREV[sec] + 7)
            n = len(ts)
            return httpx.Response(200, json={
                "open": [c - 1.0 for c in close], "high": [c + 2.0 for c in close],
                "low": [c - 3.0 for c in close], "close": close,
                "volume": [100] * n, "timestamp": ts, "open_interest": [0] * n})
        return httpx.Response(404, json={})


def make_client(fake: FakeDhan | None = None, *, fast: bool = True) -> tuple[DhanClient, FakeDhan]:
    fake = fake or FakeDhan()
    http = httpx.AsyncClient(
        base_url="https://api.dhan.co/v2",
        headers={"access-token": "tok", "client-id": "1000000001"},
        transport=httpx.MockTransport(fake.handler),
    )
    client = DhanClient("1000000001", "tok", http=http)
    if fast:
        client._quote_gate._min = 0
        client._data_gate._min = 0
    return client, fake
```

The feed tests use a real WebSocket server on `127.0.0.1`:

```python
# tests/market/test_dhan_feed.py (excerpt)
class FakeServer:
```

### 12.3 Contract suite: the guarantee that sources are interchangeable

Parametrised over `simulator` and `dhan` (fake transport). Any future source (WebSocket-only, another vendor) must pass it unchanged.

```python
# tests/market/test_contract.py
"""One suite, every source: anything that implements MarketDataSource must pass it."""

import asyncio
from datetime import timedelta

import pytest

from app.market import CapabilityError, PriceCache
from app.market.dhan.instruments import InstrumentResolver
from app.market.dhan.source import DhanDataSource
from app.market.simulator import SimulatorDataSource

from .dhan_fakes import INSTRUMENT_CSV, make_client
from .test_dhan_source import FILE, until

KNOWN = ["TCS", "INFY"]


@pytest.fixture(params=["simulator", "dhan"])
async def ctx(request, tmp_path):
    cache = PriceCache()
    if request.param == "simulator":
        src = SimulatorDataSource(cache, update_interval=0.05, seed=1)
    else:
        (tmp_path / FILE).write_text(INSTRUMENT_CSV)
        client, _ = make_client()
        src = DhanDataSource("1000000001", "tok", cache, tmp_path, client=client,
                             resolver=InstrumentResolver(tmp_path))
    await src.start(KNOWN)
    await until(lambda: all(t in cache for t in KNOWN))
    yield src, cache
    await src.stop()


@pytest.mark.asyncio
class TestSourceContract:
    async def test_metadata(self, ctx):
        src, _ = ctx
        assert src.name in {"simulator", "dhanhq"} and len(src.currency) == 3 and src.healthy

    async def test_streams_known_tickers_with_positive_prices(self, ctx):
        src, cache = ctx
        assert sorted(src.get_tickers()) == sorted(KNOWN)
        assert all(cache.get(t).price > 0 for t in KNOWN)

    async def test_is_supported_is_case_insensitive_and_rejects_junk(self, ctx):
        src, _ = ctx
        assert await src.is_supported("tcs") and not await src.is_supported("???")

    async def test_add_remove_roundtrip(self, ctx):
        src, cache = ctx
        await src.add_ticker("RELIANCE")  # supported by both fixtures' universes
        await until(lambda: "RELIANCE" in cache)
        await src.remove_ticker("reliance")
        assert "RELIANCE" not in cache and "RELIANCE" not in src.get_tickers()
        await src.remove_ticker("RELIANCE")  # no-op

    async def test_add_duplicate_is_noop(self, ctx):
        src, _ = ctx
        await src.add_ticker("TCS")
        assert src.get_tickers().count("TCS") == 1

    async def test_quotes_omit_unknown_never_zero_and_do_not_write_cache(self, ctx):
        src, cache = ctx
        q = await src.get_quotes(["TCS", "???"])
        assert "???" not in q and q["TCS"].price > 0
        assert "RELIANCE" not in cache  # on-demand quotes never add tickers to the cache

    async def test_daily_bars_sorted_and_in_range(self, ctx):
        src, _ = ctx
        end = src.latest_completed_session()
        start = end - timedelta(days=20)
        bars = await src.get_daily_bars("TCS", start, end)
        assert all(start <= b.date <= end for b in bars)
        assert [b.date for b in bars] == sorted({b.date for b in bars})
        assert all(b.low - 0.01 <= min(b.open, b.close) and max(b.open, b.close) <= b.high + 0.01
                   for b in bars)
        assert await src.get_daily_bars("???", start, end) == []

    async def test_eod_closes_omit_unknown(self, ctx):
        src, _ = ctx
        closes = await src.get_eod_closes(["TCS", "???"], on=src.latest_completed_session())
        assert set(closes) <= {"TCS"} and all(v > 0 for v in closes.values())

    async def test_stop_then_no_more_writes(self, ctx):
        src, cache = ctx
        await src.stop()
        version = cache.version
        await asyncio.sleep(0.2)
        assert cache.version == version


@pytest.mark.asyncio
async def test_default_methods_raise_capability_error():
    from app.market.interface import MarketDataSource

    class Minimal(MarketDataSource):
        async def start(self, tickers): ...
        async def stop(self): ...
        async def add_ticker(self, t): ...
        async def remove_ticker(self, t): ...
        def get_tickers(self): return []

    m = Minimal()
    with pytest.raises(CapabilityError):
        await m.get_quotes(["A"])
    with pytest.raises(CapabilityError):
        await m.get_daily_bars("A", None, None)
    with pytest.raises(CapabilityError):
        await m.get_eod_closes(["A"])
    assert await m.is_supported("anything") and m.healthy
```

### 12.4 Opt-in live tests (not in CI)

With a real, Data-API-subscribed token, run the smoke test in DHANHQ_API.md §11, then convert its findings into `@pytest.mark.live` tests (skipped unless `DHANHQ_API_KEY` is set) asserting: `ohlc.close` vs previous close, partial-candle behaviour, empty-range behaviour, rate-limit status code, and (if `DHANHQ_USE_WEBSOCKET`) one real tick within 10 s during market hours.

### 12.5 Quality evidence

- 227 passed, repeated 5× with no failures; `ruff check app tests` clean (project config: E, F, I, N, W).
- Coverage `app/market`: 96 % (uncovered: Massive error branches, SSE disconnect branches in unchanged `stream.py`, a few defensive log paths).
- Mutation check: removing the Cholesky shrinkage makes `test_non_psd_matrix_is_shrunk_not_fatal` fail.
- Bugs found *by* these tests during the build: (1) falsy empty `PriceCache` in `MarketDataService`; (2) a server disconnect after good data resetting the feed backoff (a hot loop on an expired token; caught in review and now covered by the 807 test); (3) startup race briefly showing a wrong day change; (4) wall-clock-dependent cadence in tests.

---

## 13. Risks, limitations, decisions still open

| # | Item | Mitigation / owner decision |
|---|---|---|
| 1 | No authenticated Dhan call was possible; success payloads come from the docs | Run the smoke test (DHANHQ_API.md §11) before relying on it; §7.6 shows the design does not depend on the open questions |
| 2 | Data APIs are a paid Dhan add-on | Confirm the account has it; without it, `DH-902`/`806` → unhealthy |
| 3 | Dhan universe is NSE/INR; existing DBs seeded with US tickers keep them, unpriced | `default_watchlist()` for fresh DBs; for existing DBs decide: reset, or leave `—`. Held US positions cannot be valued in Dhan mode (needs a product decision) |
| 4 | US stocks via Dhan: symbols resolve (all ten defaults present), but only a WebSocket exists and EOD has no source | Out of scope; would add a resolver + `GlobalFeed`; `get_daily_bars` stays `CapabilityError` |
| 5 | NSE holidays are not modelled | Dhan returns the last price; bars simply have no row. Add a holiday list only if needed |
| 6 | Token lasts 24 h; renewal is memory-only | Runbook §11.2; TOTP flow intentionally omitted |
| 7 | Massive stays as a lazily imported legacy tier | Delete `massive_client.py` + dependency if Dhan replaces it; update PLAN §1/§5/§6 |
| 8 | Prices are `float` (2 dp) | Matches PLAN (`REAL` columns); switch to `Decimal` only if trading maths demands it |
| 9 | Float32 prices from the feed (e.g. 1234.57 → 1234.5699…) | Rounded to 2 dp at ingestion; never compared for equality |
| 10 | `/api/market/*` routes are not in PLAN §8 | Add them (or drop the ones the frontend won't use) |
| 11 | Single user / single process | The cache and source are per-process; multi-user later means one source feeding a shared cache, which this already is |

---

## 14. Implementation plan

Do these in order; each step leaves the suite green. Commands run from `backend/`.

1. **Core types:** add `errors.py`, `calendar.py`; update `models.py`, `cache.py`, `interface.py`. `uv run --extra dev pytest` → the 73 existing tests pass; add `test_models_cache_v2.py`.
2. **Simulator:** replace `seed_prices.py`, `simulator.py`; add `synthetic_history.py`; add `test_simulator_v2.py`. Existing simulator tests must still pass untouched.
3. **Dependencies:** `uv add httpx websockets`.
4. **Dhan package:** add `dhan/{__init__,hours,client,instruments,feed,source}.py` and the Dhan tests + `conftest.py` (market-open fixture) + `dhan_fakes.py`.
5. **Factory, service, router:** replace `factory.py` (lazy imports), add `service.py`, `api.py`, update `__init__.py`; add `test_factory_v2.py`, `test_service_api.py`, `test_contract.py`.
6. **Wire the app:** in `main.py` use the lifespan from §10.2 with the DB (`default_watchlist()` for seeding; `service.sync(...)` after watchlist and position writes; `service.price_for_trade()` in the trade route; embed `service.status()` in `/api/health`).
7. **Housekeeping:** `.env.example` (§3.1); update `backend/CLAUDE.md` and `planning/MARKET_DATA_SUMMARY.md`; PLAN.md §5 (env vars), §6 (Dhan, previous close, on-demand API), §8 (routes), §12; update `market_data_demo.py` imports if needed (`SEED_PRICES` still exported).
8. **Smoke test with a real token** (DHANHQ_API.md §11); fold the answers into DHANHQ_API.md §12 and, if `net_change` is populated, simplify previous close (§7.6).
9. **Frontend:** consume `day_change_percent`, `timestamp` staleness, `currency`, `healthy` (§10.4).
10. **Docker:** ensure egress to `api.dhan.co`, `s3.ap-south-1.amazonaws.com`, and `api-feed.dhan.co` (WS), and that `DHANHQ_CACHE_DIR` is the mounted `finally-data` volume.
