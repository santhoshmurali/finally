# Market Simulator

The built-in price generator used when no Dhan token is configured (PLAN section 6). It implements the same `MarketDataSource` interface as the Dhan source ([MARKET_INTERFACE.md](MARKET_INTERFACE.md)), so nothing downstream changes. Code: `backend/app/market/simulator.py`, `seed_prices.py`, `synthetic_history.py`.

## 1. Goals

- Realistic, continuously moving **INR prices for NSE tickers**, with no network and no credentials.
- Updates every **500 ms**; correlated moves inside sectors; occasional 2 to 5% shock events for drama.
- The same universe as the Dhan source: the ten default NSE tickers and any extra symbol a user adds.
- **Reproducible** when seeded, so tests and demos are deterministic.

## 2. The model

### 2.1 GBM step

Each ticker follows geometric Brownian motion:

```text
S(t+dt) = S(t) * exp((mu - sigma^2 / 2) * dt + sigma * sqrt(dt) * Z)
```

`mu` is the annual drift, `sigma` the annual volatility and `Z` a standard normal (correlated, section 2.2). Time is measured in **NSE trading time**: `dt = 0.5 s / (252 days * 6.25 h * 3600 s)`, about 8.8e-8 years. A 0.5 s tick then moves a 25%-volatility stock by roughly 0.008%, which gives a believable day range of about 1.5% over a session of 45,000 ticks.

### 2.2 Correlation

Pairwise correlation is `0.6` inside a sector group, `0.3` otherwise (`seed_prices.py`):

| Group | Tickers |
|---|---|
| it | TCS, INFY, WIPRO |
| banks | HDFCBANK, ICICIBANK, SBIN |
| consumer | ITC, HINDUNILVR |
| (none) | RELIANCE, BHARTIARTL, LT and any added ticker: 0.3 with everyone |

The correlation matrix is rebuilt and Cholesky-factorised whenever a ticker is added or removed; independent normals `Z0` become correlated `Z = L @ Z0`. A unit test checks that the sampled correlations are 0.6 and 0.3 within tolerance.

### 2.3 Random events

Each ticker each step has a `0.001` chance of a shock: a jump of **2 to 5%**, up or down. Across ten tickers that is roughly one event every 50 seconds.

### 2.4 What "previous close" means here

The **seed price is also the previous close**: the cache is seeded with `previous_close = seed`, so day change starts at 0% and drifts as the session runs. The simulator has no market calendar: it keeps moving at any time of day (a demo needs motion).

## 3. Code structure

| Module | Role |
|---|---|
| `seed_prices.py` | data only: `DEFAULT_WATCHLIST`, `SEED_PRICES`, `TICKER_PARAMS`, `CORRELATION_GROUPS`, `TICKER_PATTERN`, `seed_price_for()` |
| `simulator.py` `GBMSimulator` | the maths: `step()`, `add_ticker()`, `remove_ticker()`, `tickers` |
| `simulator.py` `SimulatorDataSource` | the `MarketDataSource` wrapper: background task, cache writes, history |
| `synthetic_history.py` | deterministic daily bars |

## 4. Parameters

Seed prices are the real NSE closes of 2026-10-21 (so simulator and Dhan prices are close to each other): RELIANCE 1209.00, TCS 2529.00, INFY 1168.00, HDFCBANK 706.95, ICICIBANK 1385.00, SBIN 963.00, BHARTIARTL 1891.70, ITC 262.00, LT 3636.00, HINDUNILVR 1850.20, WIPRO 189.17.

`sigma` runs from 0.18 (HINDUNILVR) to 0.30 (SBIN), `mu` from 0.04 to 0.09; unknown tickers use `sigma 0.28, mu 0.05`. These are plausible, not calibrated; edit `TICKER_PARAMS`.

### 4.1 Unknown tickers

Any symbol matching `^[A-Z0-9][A-Z0-9&.\-]{0,19}$` is accepted (`M&M`, `BAJAJ-AUTO`, `ZOMATO`). Its seed price is **derived from the symbol** (`crc32` mapped into 100 to 3000 INR), so it is the same on every run, in the cache and in its history bars. Anything else raises `UnsupportedTickerError`.

## 5. `SimulatorDataSource`

- `start(tickers)`: validate symbols, build the `GBMSimulator`, seed the cache (`previous_close = seed`), start the background loop that sleeps `update_interval` (0.5 s) and writes every ticker's new price.
- `add_ticker` / `remove_ticker`: update the simulator and the cache; idempotent.
- `healthy()`: the loop task is alive.
- `daily_bars()`: `synthetic_bars()` anchored at the seed price.
- Constructor: `SimulatorDataSource(cache, update_interval=0.5, seed=None)`. `MARKET_SEED` in the environment becomes `seed` through the factory.

## 6. Synthetic end-of-day history

`synthetic_bars(ticker, start, end, anchor_price, today=None)`:

- Weekdays only, **completed days only** (never today), no holiday calendar.
- The last completed weekday closes **exactly at the anchor** (the previous close), so history and the live day change agree.
- Earlier closes walk **backwards**: `close(d-1) = close(d) / exp(r(d))` with `r(d) ~ N(0, 1.5%)` seeded by `crc32(ticker:day)`.
- Open, high, low and volume are derived from per-day seeded random numbers.
- The result for a given day does not depend on the requested range (a test compares a wide and a narrow request); this needed the walk to extend one session before the range so the first open is identical.

## 7. Determinism and testability

`GBMSimulator(..., seed=n)` uses `numpy.random.default_rng(n)`: the same seed gives the same path (`test_same_seed_gives_same_path`). `dt` is injectable so tests can use tiny steps. Tests cover: log-return standard deviation equals `sigma * sqrt(dt)` within 8%, sector correlations, 2 to 5% event sizes, add/remove, invalid symbols, cache seeding, and background updates.

## 8. Notes

- NumPy is the only extra dependency.
- The simulator is not used when a Dhan token is present, but the history tests and the default watchlist live here, so it stays part of the build.
- Prices stay positive by construction (GBM), and shocks are at most 5%.
