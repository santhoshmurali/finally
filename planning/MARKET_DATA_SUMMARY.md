# Market Data Summary

One-page digest of the FinAlly market data component (`backend/app/market/`). Sources: [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md), [MARKET_INTERFACE.md](MARKET_INTERFACE.md), [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md), [DHANHQ_API.md](DHANHQ_API.md). Status: **built and tested** (125 market tests, 100% line coverage of `app/`, plus a console demo).

## 1. What it does

Supplies live **INR prices for NSE cash equities** to the rest of the backend (SSE, trades, watchlist, LLM context). Two interchangeable sources write into one in-memory `PriceCache`; consumers only read the cache.

```text
create_market_source() -> DhanDataSource (live)  | SimulatorDataSource (default)
                                   \ writes /
                                 PriceCache
                    SSE stream | trade execution | watchlist / LLM
```

## 2. Key decisions

| Decision | Why |
|---|---|
| India only (NSE, INR) | Dhan is an Indian broker API; no US data |
| WebSocket for live prices | Push on every change, immediate last tick and previous close on subscribe, no 1 req/s REST limit |
| REST only for instrument list and daily history | No push equivalent |
| Previous close from the feed's Previous Close packet | REST `ohlc.close` becomes the current price after hours |
| Ticks stamped with receive time | Dhan encodes IST wall-clock as UTC in its trade time |
| Simulator when no token is set | Zero-setup requirement |
| Bad or expired token fails loudly | No silent fallback to fake prices |
| Caller owns the priced set | Priced tickers = watchlist + held tickers; the market package prices only what it is told |

## 3. Choosing a source

| Environment | Source |
|---|---|
| `DHAN_ACESS_TOKEN` (or `DHAN_ACCESS_TOKEN`) set, non-blank | Dhan; client ID decoded from the token (`DHAN_CLIENT_ID` overrides); surrounding quotes stripped |
| otherwise | Simulator (`MARKET_SEED=<int>` for reproducibility) |

An expired or malformed token raises `AuthenticationError` at startup.

## 4. Public API (`from app.market import ...`)

- **`PriceUpdate`**: ticker, price, previous_price (tick flash), previous_close (prior session), timestamp; derived change, direction, day_change, day_change_percent.
- **`PriceCache`**: `update`, `set_previous_close`, `get`, `get_price`, `get_all`, `remove`, `version` (SSE sends only when it changed).
- **`MarketDataSource`**: `start(tickers)`, `stop()`, `add_ticker`, `remove_ticker`, `get_tickers`, `daily_bars(ticker, start, end)`, `healthy()`.
- **Errors** (all `MarketDataError`): `UnsupportedTickerError` (400/404), `AuthenticationError` (503, unhealthy), `RateLimitError` (503), `DataUnavailableError` (502/503).
- **`DEFAULT_WATCHLIST`**: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, LT, HINDUNILVR.

Wiring contract: create the cache and source once in the FastAPI lifespan, `await source.start(initial_priced_tickers)`, mount `create_stream_router(cache)`, expose `source.healthy()` on `/api/health`. Trades price from `cache.get_price(ticker)` only (`None` means reject; never hit the network on the trade path).

## 5. SSE stream

`GET /api/stream/prices`: starts with `retry: 1000`, then `data: {...}` about every 0.5 s **only when the cache changed**, one entry per priced ticker (price, previous_price, previous_close, timestamp, change, direction, day_change, day_change_percent). When the market is closed Dhan is quiet after the first event.

## 6. Simulator

- GBM per ticker: `S(t+dt) = S(t) * exp((mu - sigma^2/2) dt + sigma sqrt(dt) Z)`, 500 ms tick, `dt` in NSE trading time (252 days x 6.25 h).
- Correlation via Cholesky: 0.6 within a sector (IT, banks, consumer), 0.3 otherwise; rebuilt on add/remove.
- Shocks: 0.001 chance per ticker per step, 2 to 5% up or down.
- Seed prices are real NSE closes of 2026-10-21; seed price doubles as previous close. `sigma` 0.18 to 0.30, `mu` 0.04 to 0.09.
- Any symbol matching `^[A-Z0-9][A-Z0-9&.\-]{0,19}$` is accepted; its seed price is derived from `crc32(symbol)` (100 to 3000 INR), so it is stable across runs.
- Deterministic synthetic daily bars: weekdays only, never today, last bar closes exactly at the anchor.
- No market calendar; keeps moving at any hour.

## 7. Dhan live source

**Credentials**: JWT token (24 h) with the client ID in the `dhanClientId` claim and expiry in `exp`. Needs an active Data API plan (`GET /v2/profile` shows `dataPlan`).

**Hosts**: REST `https://api.dhan.co/v2`; feed `wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2`; instruments `GET /v2/instrument/NSE_EQ` (no auth, redirects to S3). Egress also needs `s3.ap-south-1.amazonaws.com`.

**Limits**: history 5 req/s; quote REST 1 req/s (HTTP 429 beyond); WebSocket 5 connections, 5,000 instruments each, 100 per subscribe message.

**Flow**: download instrument list (keep `INSTRUMENT == EQUITY` and `SERIES == EQ`), resolve tickers to security IDs (unknown ticker raises before connecting), subscribe with `{"RequestCode": 15, ...}` (16 unsubscribes). Dhan immediately sends a Ticker packet (code 2, price) and a Previous Close packet (code 6) per instrument, even when closed, then pushes on each change.

**Packets**: little-endian, 8-byte header `<BHBI`; Ticker and Previous Close are 16 bytes (`<BHBIfI`); Disconnect (code 50) carries an error code. Prices are float32, rounded to 2 dp.

**Disconnect codes**: 805 too many connections (retry with backoff); 806 no Data plan, 807 token expired, 808 auth failed, 809 token invalid (fatal, no retry, unhealthy).

**Feed behaviour**: reconnect with backoff (1 s after a connection that delivered data, otherwise doubling to a 30 s cap); resubscribes the current id set; unhealthy after 3 consecutive connections with no data (Dhan drops bad sessions silently); expiry checked before each connect; bad frames and handler exceptions are logged and skipped; the `websockets` logger is pinned to INFO because it logs the token-bearing URL at DEBUG.

**History**: `POST /v2/charts/historical`, one instrument per call, `toDate` non-inclusive (client sends `end + 1 day`), timestamps are IST midnight, completed sessions only, `DH-907` (empty range, HTTP 400) maps to `[]`.

**Error mapping**: `DH-901`, `DH-902`, 806 to 810 map to `AuthenticationError`; `DH-904`, 805, HTTP 429 to `RateLimitError`; `DH-907` to empty; everything else to `DataUnavailableError`.

## 8. Verified findings (live, 2026-10-22 and 2026-10-26)

- Previous Close packet equals the last completed daily bar's close (TCS 2529.0).
- In session a busy ticker pushes about once per second; quiet tickers can go silent 20 to 46 s while the connection is fine, so never time out per ticker.
- 6-minute market-hours run: 2,349 ticks, zero reconnects, healthy throughout; all 10 tickers priced 1 s after `start()`; runtime `add_ticker` / `remove_ticker` worked.
- `add_ticker("AAPL")` raises `UnsupportedTickerError`.

## 9. Failure behaviour

Running prices are never wiped on failure: the SSE stream serves last known values and `healthy()` reports the truth. Network drops reconnect with backoff; mid-run token expiry stops the feed and marks it unhealthy. **Recovery**: generate a new token (web.dhan.co, My Profile, *Access DhanHQ APIs*), put it in `.env`, restart. Automatic renewal is deliberately not built.

## 10. Configuration and dependencies

| Variable | Meaning |
|---|---|
| `DHAN_ACESS_TOKEN` | Dhan token; absent or blank means simulator |
| `DHAN_CLIENT_ID` | Optional override of the token's client ID |
| `MARKET_SEED` | Optional integer seed for the simulator |

Runtime deps: `httpx`, `websockets`, `numpy`, `fastapi`, `uvicorn`. `prompt-toolkit` (demo group) and dev tools must be excluded from the production image.

## 11. Testing and demo

- `cd backend && uv run pytest` (163 tests including the demo); `uv run ruff check app tests demo` is clean; green on Python 3.12 and 3.14.
- Console demo: `cd backend && uv run python -m demo` (live table plus per-symbol line charts; `--plain N` for headless, `--simulator` explicit). Full-screen view needs a real Windows console.
- Defects found and fixed during testing: quoted token rejected, range-dependent synthetic bars, random unknown-ticker seeds, token leaking via `websockets` DEBUG logs, backoff reset by server disconnects, single bad frame killing the feed, unmapped exceptions from malformed replies.

## 12. Known limits and not built

- Longest live observation is 6 minutes; full-session behaviour, multi-connection limits (805), long idle connections and mid-session token expiry are unverified.
- Not built on purpose: Quote/Full/Depth/OI packets, multiple connections, market calendar and holidays, token auto-renewal, price persistence, US data.
