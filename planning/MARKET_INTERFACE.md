# Unified Market Data Interface

The Python API the rest of the FinAlly backend (SSE, trades, watchlist, LLM context) uses for prices. It hides whether prices come from **DhanHQ** (live NSE data) or the **simulator**. Both are implemented, tested and live in `backend/app/market/`.

Companions: [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md), [DHANHQ_API.md](DHANHQ_API.md), [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md).

## 1. Rules of the interface

- One abstract class, `MarketDataSource`; the Dhan source and the simulator are interchangeable.
- Sources **write** to a shared `PriceCache`; consumers **read** the cache. Nothing downstream imports a concrete source.
- Currency is **INR** and tickers are **NSE symbols** (`RELIANCE`, `TCS`, `M&M`). US tickers are not supported on either source; the simulator accepts any well-formed symbol so a demo never blocks.
- Fail loudly with one error hierarchy (`MarketDataError`); callers never see `httpx` or `websockets` exceptions.

## 2. Public surface

```python
from app.market import (
    PriceCache, MarketDataSource, create_market_source, create_stream_router,
    PriceUpdate, Bar, DEFAULT_WATCHLIST,
    MarketDataError, UnsupportedTickerError, AuthenticationError,
    RateLimitError, DataUnavailableError,
)
```

### 2.1 `PriceUpdate` (`models.py`, frozen dataclass)

| Field | Meaning |
|---|---|
| `ticker` | symbol |
| `price` | latest price, 2 dp |
| `previous_price` | the prior tick; drives the green/red flash |
| `previous_close` | prior session close; equals `price` until a real value is known |
| `timestamp` | Unix seconds, **receive time** (Dhan's own trade time is unreliable, see DHANHQ_API.md 4.4) |

Derived: `change`, `direction` (`up`/`down`/`flat` vs the prior tick), `day_change`, `day_change_percent` (vs `previous_close`, 0 when the close is 0), and `to_dict()` (the SSE payload).

### 2.2 `Bar`

`Bar(day: date, open, high, low, close, volume)`: one completed daily candle.

### 2.3 `PriceCache` (`cache.py`)

| Method | Behaviour |
|---|---|
| `update(ticker, price, timestamp=None, previous_close=None)` | store a price, returns the `PriceUpdate`. First price of a ticker is its own previous tick. An explicit `previous_close` wins, otherwise the stored one is carried forward, otherwise `price`. |
| `set_previous_close(ticker, value)` | set the close and recompute the day change of the cached price; ignored for unknown tickers |
| `get(ticker)`, `get_price(ticker)`, `get_all()` | read; `get_all()` returns a snapshot copy |
| `remove(ticker)` | drop a ticker |
| `version` | increments on every write; the SSE stream sends only when it changed |
| `len(cache)`, `ticker in cache` | |

### 2.4 `MarketDataSource` (`interface.py`)

```python
class MarketDataSource(ABC):
    currency = "INR"
    cache: PriceCache

    async def start(self, tickers: list[str]) -> None     # raises UnsupportedTickerError / AuthenticationError
    async def stop(self) -> None                           # safe to repeat
    async def add_ticker(self, ticker: str) -> None        # raises UnsupportedTickerError; idempotent
    async def remove_ticker(self, ticker: str) -> None     # drops it from the cache; idempotent
    def get_tickers(self) -> list[str]                     # sorted, upper case
    async def daily_bars(self, ticker, start, end) -> list[Bar]   # completed days, oldest first
    def healthy(self) -> bool                              # for /api/health
```

Contract details:

- `start` returns once the background task is running; prices appear in the cache shortly after (about a second for Dhan, immediately for the simulator).
- Tickers are case-insensitive on input and upper case everywhere after.
- `daily_bars` never includes today; an empty range gives `[]`.
- The caller owns the **priced set** (watchlist plus held tickers, PLAN section 1): it calls `start` with the initial set, `add_ticker` when a ticker is watched or bought, and `remove_ticker` only when the ticker is neither watched nor held.

### 2.5 Errors (`errors.py`)

| Error | Raised for | HTTP mapping suggested for routes |
|---|---|---|
| `UnsupportedTickerError` | not an NSE equity (Dhan) or malformed symbol (simulator) | 400 / 404 |
| `AuthenticationError` | missing, malformed or expired token; no Data plan; feed rejects the session | 503, health unhealthy |
| `RateLimitError` | Dhan throttling | 503 with retry |
| `DataUnavailableError` | network, 5xx, malformed replies | 502 / 503 |

All inherit `MarketDataError`.

## 3. Choosing a source: `create_market_source(cache, env=None)`

| Environment | Result |
|---|---|
| `DHAN_ACESS_TOKEN` (or `DHAN_ACCESS_TOKEN`) set and non-blank | `DhanDataSource`, client ID decoded from the token (`DHAN_CLIENT_ID` overrides) |
| otherwise | `SimulatorDataSource` (`MARKET_SEED=<int>` makes it reproducible) |

An expired or malformed token raises `AuthenticationError` immediately instead of silently falling back, so a misconfigured deployment is noticed. Surrounding quotes on the token value are stripped.

Default watchlist (`DEFAULT_WATCHLIST`): RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, LT, HINDUNILVR. They resolve on Dhan and have seed data in the simulator.

## 4. Typical call sites

```python
cache = PriceCache()
source = create_market_source(cache)           # Dhan or simulator from the environment
await source.start(DEFAULT_WATCHLIST)          # in the FastAPI lifespan
app.include_router(create_stream_router(cache))  # GET /api/stream/prices

# POST /api/watchlist
try:
    await source.add_ticker(body.ticker)
except UnsupportedTickerError:
    raise HTTPException(400, "unsupported ticker")

# trade execution: price from the cache (never call the network on the trade path)
price = cache.get_price("TCS")                 # None => not priced yet, reject the trade

# GET /api/health
{"market_healthy": source.healthy()}

# nightly valuation or history chart
bars = await source.daily_bars("TCS", date(2026, 10, 1), date(2026, 10, 21))
```

## 5. SSE stream (`stream.py`)

`GET /api/stream/prices` (PLAN section 6): an `EventSource`-compatible stream. It starts with `retry: 1000`, then sends `data: {...}\n\n` roughly every 0.5 s **when the cache changed**, with one entry per priced ticker:

```json
{"TCS": {"ticker": "TCS", "price": 2506.9, "previous_price": 2506.9, "previous_close": 2529.0,
         "timestamp": 1792690207.1, "change": 0.0, "direction": "flat",
         "day_change": -22.1, "day_change_percent": -0.8738}}
```

The loop ends when the client disconnects. When the market is closed Dhan prices do not change, so after the first event the stream is quiet; the browser keeps the last values.

## 6. Behaviour matrix

| Situation | Simulator | Dhan |
|---|---|---|
| Unknown or malformed ticker | `UnsupportedTickerError` only for malformed symbols | `UnsupportedTickerError` unless an NSE `EQ` stock |
| Previous close | the seed price | Previous Close packet from the feed |
| Market closed | keeps moving (demo mode) | last price and previous close, then quiet |
| `healthy()` | background task alive | feed task alive, no fatal auth error, fewer than 3 consecutive failed connects |
| History | deterministic synthetic bars | `POST /charts/historical` |
