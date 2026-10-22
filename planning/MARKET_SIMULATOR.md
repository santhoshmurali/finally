# Market Simulator: Approach and Code Structure

The simulator is the default price source (no `DHANHQ_API_KEY`). It must look and behave like a live market well enough to demo the whole product, while being free, offline and, for tests, **deterministic**. It implements the same `MarketDataSource` interface as the Dhan source ([MARKET_INTERFACE.md](MARKET_INTERFACE.md)), so nothing downstream can tell the difference.

This document describes the approach, the existing implementation (`backend/app/market/simulator.py`, `seed_prices.py`), the gaps versus PLAN.md and the interface, and the additions that close them.

---

## 1. Goals

| Goal | Consequence |
|---|---|
| Realistic-looking prices at ~500 ms cadence | Geometric Brownian Motion (GBM) with tiny per-tick `dt` |
| Believable cross-section | Correlated moves via a Cholesky-factored correlation matrix |
| Occasional drama | Random 2–5 % shock "events" |
| Start from sensible prices | Seed prices per ticker; **seed price = previous close** (PLAN §6) |
| Support the full interface | Quotes, `previous_close`, daily bars/EOD, ticker validation |
| Reproducible tests | Injected, seedable RNG; deterministic synthetic history |
| Any ticker the user types | Unknown but well-formed tickers get a stable, derived seed price and default parameters |
| Cheap | O(n) per tick plus one `n×n` matrix-vector product; n ≲ 50 |

Non-goals: matching real statistics tick-for-tick, order-book dynamics, intraday seasonality (open/close volatility smile), fat tails beyond the event shocks. Prices are fiction; their purpose is a convincing UI.

---

## 2. The model

### 2.1 GBM step

For each ticker, per tick:

```text
S(t+dt) = S(t) · exp( (μ − σ²/2)·dt + σ·√dt·Z )
```

- `μ` annualised drift, `σ` annualised volatility (per-ticker table, §4)
- `Z` a standard normal draw, **correlated across tickers** (§2.2)
- `dt` the tick length as a fraction of a trading year. With 252 days × 6.5 h × 3600 s = 5,896,800 trading seconds per year and a 0.5 s tick, `dt ≈ 8.48e-8`, so a typical tick moves `σ·√dt ≈ 0.0003·σ` (about 6e-5, or ~1.2 cents on a $190 stock at σ = 0.22), accumulating to realistic daily ranges (daily σ ≈ σ/√252 ≈ 1.4 %).

The `−σ²/2` term is the Itô correction that keeps `E[S]` growing at `μ`; the exponential form keeps prices strictly positive.

> **Fix needed:** `dt` must follow the configured tick interval. The current `SimulatorDataSource(update_interval=…)` does not pass a matching `dt` to `GBMSimulator`, so changing the interval changes the *speed* of the market rather than only its sampling rate. Compute `dt = update_interval / TRADING_SECONDS_PER_YEAR` when constructing the simulator (§5).

### 2.2 Correlation

Independent noise makes ten stocks look like ten unrelated random walks; real markets co-move. Build a correlation matrix `C` from sector rules, factor `C = L·Lᵀ` (Cholesky), and transform independent normals `z` into correlated `L·z`.

Current rules (`seed_prices.py`):

| Pair | ρ |
|---|---|
| both tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 |
| both finance (JPM, V) | 0.5 |
| anything with TSLA | 0.3 |
| cross-sector / unknown | 0.3 |

The matrix is rebuilt whenever a ticker is added or removed (O(n²) for the build, O(n³) for the factorisation, trivial at n < 50).

**Robustness gap:** `np.linalg.cholesky` raises `LinAlgError` if `C` is not positive-definite. With pairwise-rule matrices this *can* happen for some group mixes (e.g. a group correlation of 0.9 against cross-group 0.3 across many members). Today's constants are safe, but the factory for new profiles should fall back to a shrunk matrix: `C ← 0.95·C + 0.05·I`, retried until it factorises. See §6.3.

### 2.3 Random events

Per tick per ticker with probability `p = 0.001`: multiply the price by `1 ± U(0.02, 0.05)`. With 10 tickers at 2 ticks/s this is about one event per 50 s somewhere on the board: enough drama without constant chaos. Events are *not* applied to the correlated factor (they are idiosyncratic), which is what makes a single ticker "pop" while the rest barely move.

### 2.4 What "previous close" means here

PLAN §6: *the previous close is set from the seed price at startup, and all % change figures are measured against it.* So:

- At startup `previous_close[t] = seed_price[t]` and the first streamed price equals the seed (day change 0 %).
- Prices then random-walk away; `day_change_percent = (price − previous_close)/previous_close`.
- The simulator never "rolls over" to a new session while running; if the process runs for days, the day change simply accumulates. That is acceptable for a demo; if needed, a rollover at a fixed wall-clock time can reset `previous_close` to the current price.

(The *tick-to-tick* `previous_price` that drives the green/red flash is separate and comes from `PriceCache`.)

---

## 3. Code structure

```text
backend/app/market/
├── interface.py            MarketDataSource ABC (shared with Dhan)
├── models.py               PriceUpdate, Bar
├── cache.py                PriceCache
├── seed_prices.py          profiles: seed prices, (μ, σ), correlation groups
├── simulator.py            GBMSimulator (pure math)  +  SimulatorDataSource (asyncio, interface)
├── synthetic_history.py    synth_daily_bars() — deterministic EOD bars
└── factory.py              picks simulator when no Dhan/Massive key
```

Separation of concerns:

| Class | Responsibility | I/O? |
|---|---|---|
| `GBMSimulator` | State (prices), math, correlation, events. `step() -> {ticker: price}`. Synchronous and pure given its RNG | none |
| `synth_daily_bars` | Stateless function: ticker + params → daily bars ending at a given price | none |
| `SimulatorDataSource` | Implements `MarketDataSource`: owns the asyncio task, seeds and updates `PriceCache`, answers `is_supported/get_quotes/get_daily_bars/get_eod_closes` | cache writes |

Keeping the math in a plain class makes it trivially unit-testable (no event loop) and reusable by the demo script.

### Existing public surface (unchanged)

```python
sim = GBMSimulator(tickers=["AAPL", "MSFT"], dt=..., event_probability=0.001)
sim.step()            # -> {"AAPL": 190.01, "MSFT": 419.98}
sim.add_ticker("TSLA"); sim.remove_ticker("MSFT")
sim.get_price("AAPL"); sim.get_tickers()
```

---

## 4. Parameters (`seed_prices.py`)

Per-ticker table: seed price, `sigma` (annualised vol), `mu` (annualised drift).

| Ticker | Seed | σ | μ | Character |
|---|---|---|---|---|
| AAPL | 190 | 0.22 | 0.05 | steady |
| GOOGL | 175 | 0.25 | 0.05 | |
| MSFT | 420 | 0.20 | 0.05 | calm |
| AMZN | 185 | 0.28 | 0.05 | |
| TSLA | 250 | 0.50 | 0.03 | wild |
| NVDA | 800 | 0.40 | 0.08 | volatile, strong drift |
| META | 500 | 0.30 | 0.05 | |
| JPM | 195 | 0.18 | 0.04 | bank, low vol |
| V | 280 | 0.17 | 0.04 | payments, low vol |
| NFLX | 600 | 0.35 | 0.05 | |

Defaults for unknown tickers: `σ = 0.25`, `μ = 0.05`.

### 4.1 Profiles (to match the Dhan universe)

In Dhan mode the default watchlist is NSE equities (MARKET_INTERFACE.md §7). A user may also run the simulator *and* add Indian tickers (or vice versa). Make the tables **data, not code**, grouped as profiles, and let the lookup be profile-agnostic: one merged dict keyed by ticker, plus per-ticker sector tags that drive correlation.

```python
# seed_prices.py (additions)
# Illustrative INR seed prices: refresh occasionally; they only need to be plausible.
SEED_PRICES.update({
    "RELIANCE": 2900.0, "TCS": 3900.0, "INFY": 1500.0, "HDFCBANK": 1600.0,
    "ICICIBANK": 1100.0, "SBIN": 780.0, "BHARTIARTL": 1300.0, "ITC": 430.0,
    "LT": 3500.0, "HINDUNILVR": 2400.0,
})
TICKER_PARAMS.update({
    "RELIANCE": {"sigma": 0.24, "mu": 0.10}, "TCS": {"sigma": 0.21, "mu": 0.10},
    "INFY": {"sigma": 0.24, "mu": 0.10},     "HDFCBANK": {"sigma": 0.20, "mu": 0.10},
    "ICICIBANK": {"sigma": 0.22, "mu": 0.10}, "SBIN": {"sigma": 0.28, "mu": 0.10},
    "BHARTIARTL": {"sigma": 0.24, "mu": 0.10}, "ITC": {"sigma": 0.19, "mu": 0.08},
    "LT": {"sigma": 0.25, "mu": 0.10},        "HINDUNILVR": {"sigma": 0.17, "mu": 0.07},
})
CORRELATION_GROUPS.update({
    "in_it": {"TCS", "INFY"},
    "in_banks": {"HDFCBANK", "ICICIBANK", "SBIN"},
})
```

Generalise `_pairwise_correlation` to loop over groups: same group ⇒ that group's ρ (`tech 0.6`, `finance 0.5`, `in_it 0.65`, `in_banks 0.6`), TSLA special-case retained, otherwise `CROSS_GROUP_CORR`.

> Trading hours and "days" in the model are US-style (6.5 h) for both profiles. NSE's session is 6.25 h; the difference (4 %) is irrelevant for simulated vol.

### 4.2 Unknown tickers

Currently `random.uniform(50, 300)` per start, so the same ticker has a different price each run and tests cannot assert on it. Replace with a **stable hash-derived price** so a ticker's seed is a pure function of its symbol:

```python
import zlib

def derived_seed_price(ticker: str) -> float:
    """Stable pseudo-random price in [20, 500) from the symbol alone."""
    h = zlib.crc32(ticker.encode())
    return round(20 + (h % 48_000) / 100, 2)        # 20.00 … 499.99
```

`is_supported` for the simulator accepts any symbol matching `^[A-Z][A-Z0-9.&-]{0,14}$` (so `"???"` and empty strings are rejected, while `BRK.B`, `M&M`, `PYPL` pass). Real-market validity is not checkable offline; PLAN says unsupported tickers are rejected, and this is the simulator's definition of supported.

---

## 5. The data source (`SimulatorDataSource`)

```python
class SimulatorDataSource(MarketDataSource):
    name = "simulator"
    currency = "USD"      # cosmetic; Indian tickers render in $ unless the UI is told otherwise

    def __init__(self, price_cache, update_interval=0.5, event_probability=0.001, seed=None):
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._seed = seed
        self._sim: GBMSimulator | None = None
        self._prev_close: dict[str, float] = {}
        self._task = None
```

Lifecycle (`start/stop/add_ticker/remove_ticker/get_tickers`) as today, with these changes:

1. **`dt` follows the interval:** `GBMSimulator(tickers, dt=self._interval / GBMSimulator.TRADING_SECONDS_PER_YEAR, event_probability=…, rng=np.random.default_rng(self._seed))`.
2. **Previous close recorded at ticker add:** `self._prev_close[t] = sim.get_price(t)`, and every `cache.update(...)` passes `previous_close=self._prev_close[t]`.
3. **`remove_ticker`** also drops `_prev_close[t]`.
4. The loop catches exceptions per step (as now) and sleeps `self._interval`. Use a drift-compensated sleep (`await asyncio.sleep(max(0, next_tick - loop.time()))`) if tick regularity matters; not required.

New interface methods:

```python
async def is_supported(self, ticker: str) -> bool:
    return bool(_TICKER_RE.fullmatch(ticker.upper()))

async def get_quotes(self, tickers):
    out = {}
    for t in (x.upper() for x in tickers):
        upd = self._cache.get(t)
        if upd is not None:
            out[t] = upd                                   # live streaming ticker
        elif await self.is_supported(t):
            p = SEED_PRICES.get(t) or derived_seed_price(t)
            out[t] = PriceUpdate(t, p, p, previous_close=p)  # not streaming: seed snapshot
    return out

async def get_daily_bars(self, ticker, start, end):
    t = ticker.upper()
    if not await self.is_supported(t):
        return []
    anchor = self._prev_close.get(t) or SEED_PRICES.get(t) or derived_seed_price(t)
    params = TICKER_PARAMS.get(t, DEFAULT_PARAMS)
    last_session = last_trading_day_before(date.today())
    # Fixed lookback keeps the series identical across calls; callers slice it.
    bars = synth_daily_bars(t, last_session, HISTORY_LOOKBACK_DAYS, anchor, **params)
    return [b for b in bars if start <= b.date <= end]

async def get_eod_closes(self, tickers, on=None):
    day = on or last_trading_day_before(date.today())
    out = {}
    for t in tickers:
        bars = await self.get_daily_bars(t, day - timedelta(days=7), day)
        if bars:
            out[t.upper()] = bars[-1].close
    return out
```

Consistency rule worth stating explicitly: **the last synthetic bar's close equals the stream's `previous_close`** (both are the seed price), so the EOD history ends exactly where today's live session starts.

---

## 6. Synthetic end-of-day history (`synthetic_history.py`)

The interface promises daily bars, and the simulator has no real past. We fabricate one that is:

- **Deterministic:** same ticker + same arguments ⇒ same bars (RNG seeded from the symbol), so charts don't reshuffle on every request and tests can assert exact values.
- **Anchored:** ends at the anchor price (the previous close) on the last completed session.
- **Plausible:** consistent with the ticker's σ/μ; high ≥ max(open, close), low ≤ min(open, close); weekdays only; positive volume.

Algorithm (backwards-anchored GBM):

1. List the `n` weekday dates ending at `end` (the last completed session).
2. Draw daily log-returns `r_i = (μ − σ²/2)/252 + σ/√252 · z_i` with `z_i ~ N(0,1)` from `default_rng(crc32(ticker))`.
3. Cumulate and **shift so the final close equals the anchor**: `close_i = anchor · exp(C_i − C_n)` where `C_i = Σ_{k≤i} r_k`.
4. Open = prior close × small overnight gap (`N(0, 0.25·σ_d)`; first bar opens at its own close).
5. High/low extend beyond open/close by `|N(0, 0.5·σ_d)|`-sized wicks.
6. Volume: log-normal around a per-ticker base (hash-derived), with a mild positive correlation to `|r_i|`.

```python
# app/market/synthetic_history.py
from __future__ import annotations

import math
import zlib
from datetime import date, timedelta

import numpy as np

from .models import Bar

DAYS_PER_YEAR = 252


def weekdays_ending_at(end: date, n: int) -> list[date]:
    """The n weekday dates ending at `end` (inclusive), ascending. Holidays are not modelled."""
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


HISTORY_LOOKBACK_DAYS = 365          # weekdays generated per request; callers slice


def last_trading_day_before(d: date) -> date:
    """Most recent weekday strictly before `d`."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def synth_daily_bars(ticker: str, end: date, n: int, anchor_price: float, *,
                     mu: float = 0.05, sigma: float = 0.25) -> list[Bar]:
    """Deterministic daily OHLCV bars; the last bar's close == anchor_price."""
    if n <= 0:
        return []
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    sigma_d = sigma / math.sqrt(DAYS_PER_YEAR)
    r = (mu - 0.5 * sigma**2) / DAYS_PER_YEAR + sigma_d * rng.standard_normal(n)
    cum = np.cumsum(r)
    closes = anchor_price * np.exp(cum - cum[-1])                   # last close == anchor
    gaps = np.exp(rng.normal(0.0, 0.25 * sigma_d, n))
    opens = np.concatenate(([closes[0]], closes[:-1])) * gaps
    opens[0] = closes[0]
    wick_hi = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    wick_lo = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    highs = np.maximum(opens, closes) * (1 + wick_hi)
    lows = np.minimum(opens, closes) * (1 - wick_lo)
    base_vol = 500_000 + (zlib.crc32(ticker[::-1].encode()) % 9_500_000)
    vols = base_vol * np.exp(rng.normal(0.0, 0.3, n)) * (1 + 20 * np.abs(r))
    return [
        Bar(d, round(float(o), 2), round(float(h), 2), round(float(l), 2),
            round(float(c), 2), int(v))
        for d, o, h, l, c, v in zip(weekdays_ending_at(end, n), opens, highs, lows, closes, vols)
    ]
```

Rounding to 2 dp can in rare cases break `high ≥ max(open, close)` by a rounding hair only if wicks are ~0; the wick draws use `abs(normal)`, and the invariant is tested with a tolerance of 0.01.

History length: the series is a function of `(ticker, end, n)`, and a different `n` for the same end date changes earlier bars (the RNG stream is consumed differently). To keep charts stable across requests, `get_daily_bars` always generates a **fixed lookback** (`HISTORY_LOOKBACK_DAYS = 365` weekdays ending at the last session) and slices to `[start, end]`. Requests reaching further back than the lookback simply return fewer bars.

---

## 7. Determinism and testability

Inject the RNG instead of using module-level `numpy.random` / `random`:

```python
class GBMSimulator:
    def __init__(self, tickers, dt=DEFAULT_DT, event_probability=0.001, rng=None):
        self._rng = rng or np.random.default_rng()
        ...
    # in step():
    z = self._rng.standard_normal(n)
    ...
    if self._rng.random() < self._event_prob:
        shock = self._rng.uniform(0.02, 0.05) * (1 if self._rng.random() < 0.5 else -1)
```

`MARKET_SEED=42` ⇒ identical price paths on every run (useful for demos, screenshots and the Playwright suite). Without it, runs differ.

Suggested tests (existing suite already covers the basics; add the rest):

| Test | Assertion |
|---|---|
| Positivity | After 100k steps, all prices > 0 |
| GBM moments | Over many seeded paths, mean log-return ≈ `(μ − σ²/2)·T`, std ≈ `σ√T` (within a few standard errors) |
| Correlation | Sample correlation of tech-pair log-returns ≈ 0.6 over a long seeded run |
| Cholesky fallback | A non-PSD matrix is shrunk and factorises |
| Events | With `event_probability=1.0`, every step applies a 2–5 % shock; with `0.0`, none |
| Add/remove | Add rebuilds `L`; remove keeps others' prices unchanged |
| Seeded repeatability | Two simulators with `rng=default_rng(7)` produce identical sequences |
| `dt` coupling | `update_interval=1.0` ⇒ per-step variance ≈ 2× that of 0.5 s |
| Previous close | First cached `PriceUpdate.previous_close == seed price`; `day_change_percent == 0` initially |
| History | Ascending dates, weekdays only, last close == anchor, OHLC invariants, identical on repeat calls |
| Interface contract | Shared suite with the Dhan source's fake (MARKET_INTERFACE.md §10) |
| `is_supported` | `PYPL` ✓, `BRK.B` ✓, `""` ✗, `"AA PL"` ✗ |

---

## 8. Operational notes

- **Cost:** a 10-ticker step is ~10 `exp` calls + a 10×10 mat-vec: microseconds. The 500 ms loop is idle > 99.9 % of the time.
- **Thread-safety:** the loop runs on the event loop; `PriceCache` has its own lock for readers on other threads. `GBMSimulator` itself is *not* thread-safe; call `add_ticker`/`remove_ticker` from the same loop (the async wrappers already do).
- **Warm start:** `start()` seeds the cache with the seed prices **before** the first tick so the first SSE event and the first API call already have data.
- **Large watchlists:** Cholesky refactor on every add is O(n³); at n = 100 that is still ≈ 1 ms. No batching needed.
- **Logging:** events at DEBUG only; one INFO line on start with ticker count and whether a seed is set.
- **Currency caveat:** the simulator does not convert; its `currency` is "USD" even if the user adds `TCS`. If the Indian profile is used with the simulator, the UI should read currency from the *ticker's* profile rather than the source. This is cosmetic and can be deferred.

---

## 9. Gaps in the current implementation versus this design (checklist)

| # | Gap | Where | Fix |
|---|---|---|---|
| 1 | No `previous_close`; cache's "previous" is the previous tick, but PLAN asks % change vs previous close | `cache.py`, `simulator.py` | §2.4, MARKET_INTERFACE.md §4 |
| 2 | `dt` not tied to `update_interval` | `SimulatorDataSource.start` | §2.1 / §5 |
| 3 | Global RNGs (`np.random`, `random`); no seed | `GBMSimulator.step` | §7 |
| 4 | Unknown tickers get a random price on each run | `_add_ticker_internal` | §4.2 |
| 5 | No `is_supported`, quotes, bars, EOD | `SimulatorDataSource` | §5, §6 |
| 6 | Cholesky can raise `LinAlgError` for odd group mixes | `_rebuild_cholesky` | shrinkage fallback below |
| 7 | Only US seed data | `seed_prices.py` | §4.1 |

Shrinkage fallback for gap 6:

```python
def _rebuild_cholesky(self) -> None:
    n = len(self._tickers)
    if n <= 1:
        self._cholesky = None
        return
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            corr[i, j] = corr[j, i] = self._pairwise_correlation(self._tickers[i], self._tickers[j])
    for _ in range(10):
        try:
            self._cholesky = np.linalg.cholesky(corr)
            return
        except np.linalg.LinAlgError:
            corr = 0.9 * corr + 0.1 * np.eye(n)       # shrink toward independence
    self._cholesky = None                               # degrade to independent moves
```
