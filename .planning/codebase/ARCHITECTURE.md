---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
<!-- refreshed: 2026-10-27 -->
# Architecture

**Analysis Date:** 2026-10-27

## Scope and Status

Only the market data layer (`backend/app/market/`) and the console demo (`backend/demo/`) exist as code. Everything else in `planning/PLAN.md` is planned, not present: the SQLite database (`backend/db/`), portfolio and trade APIs, watchlist API, LLM chat, the FastAPI app and lifespan wiring, `/api/health`, the Next.js frontend, the Dockerfile and scripts, and Playwright E2E tests. Sections below describe the planned shape only where the spec fixes it, and say so.

## System Overview

```text
┌──────────────────────────────────────────────────────────────────┐
│                    Price sources (interchangeable)               │
│  ┌──────────────────────────┐   ┌────────────────────────────┐   │
│  │ SimulatorDataSource      │   │ DhanDataSource             │   │
│  │ `simulator.py` (GBM)     │   │ `dhan/source.py`           │   │
│  └────────────┬─────────────┘   │  ├─ DhanFeed (WebSocket)   │   │
│               │                 │  ├─ DhanClient (REST)      │   │
│               │                 │  └─ InstrumentResolver     │   │
│               │                 └─────────────┬──────────────┘   │
└───────────────┼───────────────────────────────┼──────────────────┘
                │ cache.update / set_previous_close               │
                ▼                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  PriceCache  `backend/app/market/cache.py`  (in-memory, locked)  │
│  latest PriceUpdate per ticker, monotonically rising `version`   │
└───────────────┬──────────────────────────────┬───────────────────┘
                │ get_all() / version          │ get_price()
                ▼                              ▼
┌──────────────────────────────┐   ┌────────────────────────────────┐
│ SSE stream                   │   │ Consumers (planned)            │
│ `market/stream.py`           │   │ trades, watchlist, portfolio,  │
│ GET /api/stream/prices       │   │ LLM context                    │
└──────────────┬───────────────┘   └────────────────────────────────┘
               ▼
        Browser EventSource (frontend not yet present)

Console demo `backend/demo/` consumes the same MarketDataSource and PriceCache directly, without HTTP.
```

## Pattern Overview

**Overall:** Producer/consumer through a shared in-memory cache, with a strategy-style abstract source interface selected at startup.

**Key Characteristics:**
- One `MarketDataSource` ABC (`backend/app/market/interface.py`) with two implementations; all downstream code only sees the ABC and `PriceCache`.
- A source owns its own background `asyncio` task and writes into the cache. Consumers never call the source for prices; they read the cache.
- The caller owns the priced set: it calls `add_ticker` / `remove_ticker`. The source does not infer the watchlist or holdings.
- Single process, single event loop. No database, queue, or message bus in the market layer.
- Errors are funneled into one hierarchy rooted at `MarketDataError` (`backend/app/market/errors.py`), so API layers can map them to 4xx/5xx.
- Currency is INR throughout (`MarketDataSource.currency = "INR"`); the interface is documented as NSE-only.

## Layers

**Interface layer (contract):**
- Purpose: Define what every price source must do.
- Location: `backend/app/market/interface.py`, `backend/app/market/models.py`, `backend/app/market/errors.py`
- Contains: `MarketDataSource` ABC (`start`, `stop`, `add_ticker`, `remove_ticker`, `get_tickers`, `daily_bars`, `healthy`), `PriceUpdate` and `Bar` frozen dataclasses, the error hierarchy.
- Depends on: `cache.py` (only for the constructor type).
- Used by: `factory.py`, `simulator.py`, `dhan/source.py`, `demo/live_console.py`, all tests under `backend/tests/market/`.

**State layer (hand-off):**
- Purpose: Hold the latest price per ticker and version it for streaming.
- Location: `backend/app/market/cache.py`
- Contains: `PriceCache` with `update`, `set_previous_close`, `get`, `get_price`, `get_all`, `remove`, `version`. Guarded by `threading.Lock` (Dhan packets and the stream run on the same loop, the lock is a cheap safety net).
- Depends on: `models.py`.
- Used by: every source (writes), `stream.py` and the demo (reads).
- Rule: `previous_price` is the prior tick (drives UI flash); `previous_close` is the prior session close (drives day change). The first write for a ticker sets `previous_price == price`.

**Source layer (producers):**
- Purpose: Produce `PriceUpdate`s into the cache and serve daily history.
- Location: `backend/app/market/simulator.py` (+ `seed_prices.py`, `synthetic_history.py`); `backend/app/market/dhan/` (`source.py`, `feed.py`, `client.py`, `packets.py`, `instruments.py`, `auth.py`).
- Depends on: `interface.py`, `cache.py`, `models.py`, `errors.py`; Dhan source also depends on `httpx`, `websockets`.
- Used by: `factory.py` only.

**Selection layer (composition root for market data):**
- Purpose: Choose the source from environment variables.
- Location: `backend/app/market/factory.py` (`create_market_source(cache, env=None)`)
- Behavior: If a Dhan token is present (`DHAN_ACESS_TOKEN`, or `DHAN_ACCESS_TOKEN`), build `DhanDataSource` with credentials parsed from the token; else build `SimulatorDataSource` (optionally seeded by `MARKET_SEED`).
- Note: Token parsing raises `AuthenticationError` on malformed or expired tokens. There is no silent fallback to the simulator (per `planning/PLAN.md` section 5).

**Transport layer (HTTP):**
- Purpose: Expose cached prices to browsers over SSE.
- Location: `backend/app/market/stream.py`
- Contains: `create_stream_router(cache, interval=0.5)` returns an `APIRouter` with prefix `/api/stream`, route `GET /prices`.
- Depends on: `PriceCache`, FastAPI, `StreamingResponse`.
- Used by: the future FastAPI app (not yet present).

**Presentation layer (console):**
- Purpose: Live terminal view of the watchlist with per-symbol line charts.
- Location: `backend/demo/` (`__main__.py`, `live_console.py`, `render.py`)
- Depends on: `app.market` public API (`create_market_source`, `PriceCache`, `DEFAULT_WATCHLIST`, `MarketDataError`), `prompt-toolkit` (demo group).
- Used by: `uv run --group demo python -m demo` from `backend/`.

## Data Flow

### Price Path (Dhan, live)

1. `create_market_source` returns `DhanDataSource` (`backend/app/market/factory.py`).
2. `DhanDataSource.start(tickers)` downloads the instrument list if no resolver was injected (`dhan/instruments.py`), maps tickers to security IDs (unknown tickers fail first), records the ticker set, subscribes via `DhanFeed.subscribe`, and creates the `dhan-feed` task running `DhanFeed.run()` (`backend/app/market/dhan/source.py`).
3. `DhanFeed` (`backend/app/market/dhan/feed.py`) keeps one WebSocket, sends subscribe messages in batches of at most 100 instruments (`MAX_INSTRUMENTS_PER_MESSAGE`), reconnects with backoff, and parses binary packets via `packets.parse_packet`.
4. Each packet goes to `DhanDataSource._on_packet`: a `Tick` becomes `cache.update(ticker, price, previous_close=...)`; a `PreviousClose` is stored in `_previous_close` and applied with `cache.set_previous_close`. Only segment-matching packets for subscribed tickers are written.
5. `PriceCache` increments `version`.

### Price Path (simulator, default)

1. `SimulatorDataSource` (`backend/app/market/simulator.py`) wraps `GBMSimulator`, which steps all tickers every 0.5 s using correlated GBM (Cholesky of a group-correlation matrix from `seed_prices.py`) plus rare shock events (`EVENT_PROBABILITY`, `EVENT_RANGE`).
2. Seed prices from `SEED_PRICES` double as the initial previous close.
3. Results are written to the cache the same way as Dhan ticks.

### SSE Stream

1. Client opens `GET /api/stream/prices` (`stream.py`, `price_events`).
2. The generator first yields `retry: 1000`, then loops every `STREAM_INTERVAL` (0.5 s) until the client disconnects.
3. It emits a `data:` event only when `cache.version` changed, containing `{ticker: PriceUpdate.to_dict()}` for every cached ticker (watchlist plus held, as the caller maintains the set).

### Daily History

1. `source.daily_bars(ticker, start, end)`.
2. Dhan: `DhanClient.daily_bars` (`dhan/client.py`) calls the REST history endpoint with a minimum 0.2 s gap between requests (`MIN_REQUEST_GAP`) and maps HTTP and Dhan error codes to the `MarketDataError` hierarchy.
3. Simulator: `synthetic_bars` in `synthetic_history.py`.

### Ticker Lifecycle (caller contract)

1. Watchlist add or first buy: caller calls `source.add_ticker(t)`; unknown tickers raise `UnsupportedTickerError`.
2. Watchlist removal while not held: caller calls `source.remove_ticker(t)`; the source unsubscribes and drops the cache entry.
3. Trades price only from `cache.get_price(t)`; `None` means not yet priced and the trade is rejected (planned behaviour, per PLAN.md section 13).

**State Management:**
- Prices: process-wide `PriceCache` instance, created once in the (future) FastAPI lifespan.
- Ticker set: held inside each source (`_tickers` set in Dhan; `GBMSimulator._tickers` in the simulator).
- Portfolio, cash, watchlist persistence: not implemented (planned SQLite in `backend/db/`).

## Key Abstractions

**`MarketDataSource` (ABC):**
- Purpose: Uniform lifecycle and query surface for any price provider.
- Examples: `backend/app/market/interface.py`, implemented by `backend/app/market/simulator.py` (`SimulatorDataSource`) and `backend/app/market/dhan/source.py` (`DhanDataSource`).
- Pattern: Template-free ABC; each source owns its background task; `stop()` must be safe to call twice.

**`PriceCache` / `PriceUpdate`:**
- Purpose: Single source of truth for latest prices; immutable snapshot records.
- Examples: `backend/app/market/cache.py`, `backend/app/market/models.py`.
- Pattern: Writers replace whole frozen `PriceUpdate` objects; readers get copies (`get_all` returns a dict copy).

**`Credentials`:**
- Purpose: Dhan token, client ID and expiry, with a redacting `__repr__`.
- Examples: `backend/app/market/dhan/auth.py`.
- Pattern: Parsed once from the JWT in `factory.py`; never logged.

**Packets and feed (Dhan binary protocol):**
- Purpose: Decode Live Market Feed frames into typed records (`Tick`, `PreviousClose`, `Disconnect`).
- Examples: `backend/app/market/dhan/packets.py`, `backend/app/market/dhan/feed.py`.
- Pattern: Pure parser `parse_packet(bytes) -> Packet`; feed takes an injectable `connect` callable for tests (`backend/tests/market/dhan_fakes.py`).

**`InstrumentResolver`:**
- Purpose: NSE symbol to Dhan security ID mapping, built from Dhan's public instrument list.
- Examples: `backend/app/market/dhan/instruments.py`.
- Pattern: Injected into `DhanDataSource` via the `resolver=` keyword for tests.

**Seed data as configuration:**
- Purpose: `DEFAULT_WATCHLIST`, `SEED_PRICES`, `TICKER_PARAMS`, `CORRELATION_GROUPS` are plain module-level dicts/lists in `backend/app/market/seed_prices.py`, shared by the simulator and the public `app.market` API.

## Entry Points

**Market package import:**
- Location: `backend/app/market/__init__.py`
- Triggers: Any `from app.market import ...`.
- Responsibilities: Re-exports the public API (`create_market_source`, `create_stream_router`, `PriceCache`, `MarketDataSource`, errors, `DEFAULT_WATCHLIST`).

**Console demo:**
- Location: `backend/demo/__main__.py` (delegates to `backend/demo/live_console.py:main`)
- Triggers: `cd backend && uv run --group demo python -m demo`.
- Responsibilities: Builds a cache and source via the factory, subscribes the default watchlist, runs the prompt-toolkit application with live table and charts; supports add and remove of symbols.

**Planned application entry (not present):**
- Location: would be a FastAPI app under `backend/app/` (no `main.py` or `app.py` exists yet).
- Planned responsibilities per `planning/PLAN.md` section 13 contract: create `PriceCache`, `create_market_source`, `await source.start(...)` in lifespan, `await source.stop()` on shutdown, mount `create_stream_router(cache)`, report `source.healthy()` from `/api/health`.

## Architectural Constraints

- **Threading:** Single asyncio event loop. Dhan feed and stream are coroutines; the `PriceCache` lock is a `threading.Lock` used inside synchronous methods only.
- **Global state:** No module-level mutable singletons in `backend/app/market/`. The cache is an explicit object passed in. Seed/param tables in `seed_prices.py` are read-only by convention.
- **Circular imports:** None detected. Dependency direction is `dhan/*` -> `interface`/`cache`/`models`/`errors`; `simulator.py` and `dhan/*` never import `factory.py`; `factory.py` imports both sources.
- **Source-specific behavior leaking:** `DhanDataSource.add_ticker` and `daily_bars` use `self._resolver` directly, so they assume `start()` has run. Calling them earlier raises `AttributeError` on `None`.
- **Caller-owned priced set:** Removing a ticker from the watchlist while it is still held would drop its price; the caller must check holdings first (planned logic).
- **Single-process:** The cache is in memory; a second process or worker would have its own prices. Consistent with the single-container design in PLAN.md section 3.

## Anti-Patterns

### Reading prices from the source instead of the cache

**What happens:** Code that calls a source method to get a live price (there is none; only `daily_bars` and `get_tickers` exist on the source).
**Why it's wrong:** Bypasses the version and staleness model and ties consumers to a specific source.
**Do this instead:** Read `cache.get_price(ticker)` or `cache.get(ticker)` (see `backend/app/market/cache.py`).

### Hard-coding `SimulatorDataSource` or `DhanDataSource` in consumers

**What happens:** Importing a concrete source into routes or trade code.
**Why it's wrong:** Defeats the one-interface design in PLAN.md section 6.
**Do this instead:** Depend on `MarketDataSource` and build through `create_market_source` in `backend/app/market/factory.py`.

### Adding prices to the cache outside a source

**What happens:** Writing `cache.update` from route handlers or tests that are not sources.
**Why it's wrong:** Mixes provider data with application state and skips the Dhan previous-close handling.
**Do this instead:** Use a fake source implementing `MarketDataSource` for tests (see `backend/tests/market/test_factory_stream.py`).

## Error Handling

**Strategy:** Typed exception hierarchy; library exceptions are converted inside the market package.

**Patterns:**
- All market failures derive from `MarketDataError` (`backend/app/market/errors.py`): `UnsupportedTickerError`, `AuthenticationError` (not retryable), `RateLimitError` (backoff), `DataUnavailableError` (network, 5xx, malformed).
- The feed stops retrying on authentication disconnect codes (`AUTH_DISCONNECT_CODES` in `backend/app/market/dhan/feed.py`) and marks the source unhealthy; `healthy()` combines task liveness and `feed.healthy`.
- Feed reconnects use exponential backoff capped at `max_backoff` (30 s by default).

## Cross-Cutting Concerns

**Logging:** Standard `logging` via `logger = logging.getLogger(__name__)` in `dhan/feed.py`; the `websockets` logger is clamped to INFO so the token-bearing URL is not logged at DEBUG.
**Validation:** Ticker symbols are upper-cased by sources; unknown symbols rejected at the resolver. Token format checked in `dhan/auth.py`.
**Authentication:** Dhan only, via the access token in the environment (no user auth; single-user per PLAN.md section 7).
**Configuration:** Environment variables read in `factory.py` and `dhan/auth.py`; no settings module yet.

---

*Architecture analysis: 2026-10-27*
