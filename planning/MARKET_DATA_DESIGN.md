# Market Data Backend: Design

How `backend/app/market/` is built: a Dhan WebSocket live source and a simulator behind one interface, writing into one cache. This is the as-built design; every statement here is covered by a unit test or a recorded live check.

Related: [MARKET_INTERFACE.md](MARKET_INTERFACE.md) (the API), [DHANHQ_API.md](DHANHQ_API.md) (the provider), [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the fallback).

## 1. Scope and decisions

| Decision | Rationale |
|---|---|
| India only: NSE cash equities, INR | Dhan is an Indian broker API. There is no REST quote or history for US stocks, so US support was dropped. |
| **WebSocket is the live source** | Push gives a price on every change, a Previous Close packet, and immediate last-tick-on-subscribe, with no REST quote rate limit (1 request/s). |
| REST only for the instrument list and daily history | These have no push equivalent. |
| Previous close comes from the feed | REST `ohlc.close` is the *current* close after hours and `net_change` was 0 (DHANHQ_API.md 6). |
| Ticks are stamped with receive time | Dhan encodes IST wall-clock as UTC in the trade time (DHANHQ_API.md 4.4). |
| Simulator when no token is set | PLAN requirement: runs with zero setup. |
| Misconfigured token fails loudly | An expired or malformed token raises at startup; no silent fallback to fake prices. |
| The caller owns the priced set | The market package prices what it is told to; the watchlist/portfolio layer decides which tickers (watchlist plus held, PLAN section 1). |
| Out of scope here | Massive/US data, orders, token renewal, a market calendar, SQLite persistence of prices. |

## 2. Architecture

```text
 .env / environment
        |
 create_market_source() --------------------------+
        |                                         |
  DhanDataSource                          SimulatorDataSource
   |  InstrumentResolver (REST, once)       |  GBMSimulator (500 ms loop)
   |  DhanFeed (WebSocket task) -> packets  |
   |  DhanClient (REST history)             |
        \________________  writes  _________/
                          v
                     PriceCache  (latest PriceUpdate per ticker, version counter)
                          |
        +-----------------+------------------+
   SSE stream         trade execution     watchlist / LLM context
```

### 2.1 Modules (`backend/app/market/`)

| Module | Responsibility |
|---|---|
| `models.py` | `PriceUpdate`, `Bar` |
| `errors.py` | `MarketDataError` hierarchy |
| `cache.py` | `PriceCache` |
| `interface.py` | `MarketDataSource` ABC |
| `factory.py` | `create_market_source()` |
| `stream.py` | SSE router `GET /api/stream/prices` |
| `seed_prices.py`, `simulator.py`, `synthetic_history.py` | simulator |
| `dhan/auth.py` | token to `Credentials` (client ID, expiry), env parsing |
| `dhan/packets.py` | binary packet decoder |
| `dhan/instruments.py` | ticker to security ID |
| `dhan/client.py` | REST client: daily history, error mapping, 5 req/s spacing |
| `dhan/feed.py` | WebSocket loop: subscribe, reconnect, backoff, fatal-auth handling |
| `dhan/source.py` | `DhanDataSource`: ties the above to the cache |

### 2.2 Data flow (Dhan)

1. `start(tickers)` downloads the NSE instrument list (about 1.6 MB), resolves every ticker (an unknown one raises `UnsupportedTickerError` **before** anything connects), subscribes them on the feed and launches the feed task.
2. The feed connects, sends the subscribe message(s) (100 ids max per message), then reads packets.
3. For each subscribed ticker Dhan immediately sends a **Ticker** packet (price) and a **Previous Close** packet. `DhanDataSource._on_packet` turns them into `cache.update(ticker, price, previous_close=...)` and `cache.set_previous_close(...)`. The previous close is remembered per ticker, so it applies whichever packet arrives first and survives later ticks.
4. `add_ticker` / `remove_ticker` send incremental subscribe / unsubscribe messages on the live socket; the feed's id set is what is re-subscribed after a reconnect.

## 3. The Dhan feed in detail (`dhan/feed.py`)

| Concern | Behaviour | Test |
|---|---|---|
| Subscribe batching | 100 ids per message | `test_subscriptions_are_batched_by_100` |
| Reconnect | any `WebSocketException` / `OSError` or normal close: sleep, reconnect, resubscribe the current id set | `test_reconnects_and_resubscribes_after_drop` |
| Backoff | 1 s after a connection that delivered data; otherwise doubles per failure, capped at 30 s. A server disconnect packet is *not* data, so repeated disconnects (e.g. 805) keep backing off | `test_backoff_doubles_and_caps...`, `test_repeated_server_disconnects_back_off_and_turn_unhealthy` |
| Health | unhealthy after 3 consecutive connections with no data (the bad-token signature, since Dhan drops silently); healthy again after a connection that delivers data | `test_unhealthy_after_repeated_failures_and_recovers` |
| Fatal auth | disconnect packet 806 to 809 stops the loop and sets `error`; no retry | `test_auth_disconnect_is_fatal` |
| Other disconnects | e.g. 805: reconnect with backoff | `test_other_disconnect_reconnects` |
| Token expiry | checked before every connect attempt; expired means stop with `AuthenticationError` | `test_expired_token_stops_without_connecting` |
| Secrets | the URL contains the token; the feed logs only the exception class name, and pins the `websockets` logger to INFO because that library logs the full URL, token included, at DEBUG | `test_websockets_debug_logging_cannot_leak_the_token` |
| Bad frames | an undecodable packet is logged and skipped; an exception in the packet handler is logged and the feed keeps running | `test_undecodable_frames_are_skipped`, `test_failing_callback_does_not_kill_the_feed` |
| Subscribe on a dropped socket | ignored; the id is already tracked and is resubscribed on reconnect | `test_subscribe_on_a_dropped_socket_keeps_the_id_for_reconnect` |
| Quiet market | silence is not a failure; there is no inactivity timeout | |

## 4. Configuration

| Variable | Required | Meaning |
|---|---|---|
| `DHAN_ACESS_TOKEN` | no | Dhan access token. Present: live Dhan data. Absent or blank: simulator. `DHAN_ACCESS_TOKEN` also accepted. Surrounding quotes are stripped. |
| `DHAN_CLIENT_ID` | no | Overrides the client ID inside the token |
| `MARKET_SEED` | no | Integer seed for a reproducible simulator |

`.env.example` documents them; `.env` is gitignored. The token is a secret: `Credentials.__repr__` omits it and logs never include the feed URL.

Dependencies (`backend/pyproject.toml`, locked in `uv.lock`): `httpx`, `websockets`, `numpy`, `fastapi`, `uvicorn` (the server PLAN section 11 runs); `prompt-toolkit` in the `demo` group (a default group, like `dev`; leave both out of the production image); dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`. Egress needed for Dhan: `api.dhan.co`, `api-feed.dhan.co`, and `s3.ap-south-1.amazonaws.com` (the instrument list redirect).

## 5. Failure matrix

| Failure | Detected by | Result |
|---|---|---|
| Token missing/blank | factory | simulator |
| Token malformed or expired at startup | `credentials_from_token` | `AuthenticationError` from `create_market_source` |
| Unknown ticker at startup | resolver | `UnsupportedTickerError` from `start`, nothing connects |
| Unknown ticker later | resolver | `UnsupportedTickerError` from `add_ticker`; state unchanged |
| Token expires or is revoked mid-run | disconnect 807/809 or pre-connect check | feed stops, `healthy()` False; cache keeps last prices |
| No Data plan | disconnect 806 | same as above |
| Network drop | connection error | reconnect with backoff; healthy again once data flows |
| Dhan silently drops a bad session | 3 data-less connections | unhealthy, keeps retrying at the 30 s cap |
| History rate limited / 5xx | `DhanClient` | `RateLimitError` / `DataUnavailableError` |
| History range with no data | `DH-907` | empty list |
| Instrument list download fails | resolver | `DataUnavailableError` from `start` |

Running prices are never wiped on failure: the SSE stream keeps serving the last known values, and `healthy()` tells `/api/health` the truth.

## 6. Token runbook

Dhan tokens last 24 hours. When one expires the source goes unhealthy (feed stopped, `error` set). To recover: generate a new token (web.dhan.co, My Profile, *Access DhanHQ APIs*), put it in `.env`, restart the container. Automatic renewal (TOTP or `RenewToken`) is deliberately not built; it needs a PIN/TOTP secret, a heavier credential commitment than this project should require by default.

## 7. Testing

`cd backend && uv run pytest` runs 163 tests (125 for `app/market`, 38 for the console demo), **100% line coverage of `app/`** (`--cov=app`), also green on Python 3.12 (the Docker runtime) and 3.14. `uv run ruff check app tests demo` is clean.

| Test file | Covers |
|---|---|
| `test_models_cache.py` | `PriceUpdate` maths, `PriceCache` previous-close rules and versioning |
| `test_dhan_auth.py` | JWT decode, expiry, quotes, both env spellings |
| `test_dhan_packets.py` | packet decoding including bytes captured from the live feed |
| `test_dhan_instruments.py` | CSV filtering, case-insensitive lookup, redirect-following download |
| `test_dhan_client.py` | history parsing (IST dates, non-inclusive `toDate`), both error body shapes, malformed replies, request spacing |
| `test_dhan_feed.py` | the feed table in section 3, against a scripted fake WebSocket (`dhan_fakes.py`) |
| `test_dhan_source.py` | fake socket to feed to cache end to end, add/remove, health, shutdown |
| `test_simulator.py` | GBM statistics, correlation, events, determinism, source behaviour |
| `test_synthetic_history.py` | anchoring, weekdays, range independence |
| `test_factory_stream.py` | source selection, SSE framing and change detection |

Real-service checks (not part of CI because they need a token and network) are recorded in DHANHQ_API.md section 9, including a 6-minute run during market hours.

## 8. Defects found by testing, and fixed

| Defect | How it surfaced | Fix |
|---|---|---|
| Quoted token (`"eyJ..."`) was sent with the quote characters and rejected (`DH-901`) | first run against the real service | strip quotes in `token_from_env`; regression test |
| A synthetic bar's open depended on the requested range | a wide vs narrow range comparison test | walk one session before the range |
| Unknown-ticker seed was random per call, so history could not anchor to it | design review | seed derived from the symbol |
| SSE test hung | `httpx.ASGITransport` buffers whole responses | test the route function directly; verify streaming against uvicorn |
| Code review: server disconnects reset the backoff, so the feed would reconnect every second and look healthy | review of the feed | only real data counts as received |
| Code review: one undecodable frame or a raising handler would kill the feed task | review of the feed | log and skip; regression tests |
| Raw access token written to the logs when an app sets DEBUG (`websockets` logs the connection URL) | live check with the root logger at DEBUG: 1 log line contained the token | `websockets` logger pinned to INFO; 0 lines afterwards, regression test |
| Code review: malformed Dhan replies leaked `KeyError`/`JSONDecodeError`; a non-object JWT payload leaked `TypeError`; `uvicorn` was missing | review | mapped to `DataUnavailableError` / `AuthenticationError`; dependency added |

## 9. Console demo (`backend/demo/`)

A way to watch the feed live without the rest of the platform. Run `uv run python -m demo` (see Docs/help.md). It is a client of the public API only: `create_market_source`, `PriceCache`, `add_ticker` / `remove_ticker`.

| Module | Role |
|---|---|
| `demo/render.py` | pure functions: block-character `sparkline`, `PriceHistory` (fixed window per symbol), `build_rows`, `table_fragments`, `parse_command` |
| `demo/live_console.py` | `Demo` (watchlist state and commands), the full-screen `prompt_toolkit` app, a headless `--plain N` runner, the CLI |

Design points:

- **Chart points are sampled once per interval (default 1 s)** from the cache, not per tick, so all symbols scroll at the same speed and a quiet stock shows a flat line instead of stalling. The window is 40 points by default.
- **The vertical scale is the window's low to high**, widened to at least 0.05% of the price so one 0.05 tick does not look like a crash.
- **The UPDATED column is the receive time of the last tick**, which makes stale (quiet or closed-market) symbols visible.
- Default watchlist is `DEFAULT_WATCHLIST`. An expired token stops the demo with a message; there is no simulator fallback (`--simulator` is explicit).
- The full-screen view needs a real Windows console (PowerShell, cmd, Windows Terminal); in other shells `--plain` works and a clear message is printed instead of a stack trace.
- Tests: pure helpers directly, the app through typed input (`create_pipe_input`), and the CLI paths (headless run, expired token, wrong terminal).

## 10. Not built, on purpose

- Dhan Quote/Full packets, market depth, OI: FinAlly needs price and previous close.
- Multiple WebSocket connections (one handles 5,000 instruments).
- Market calendar and holidays: Dhan history skips non-trading days itself; the simulator ignores them.
- Persisting prices: prices are an in-memory cache; portfolio snapshots belong to the database layer.
