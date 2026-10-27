---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# External Integrations

**Analysis Date:** 2026-10-27

## APIs & External Services

**Market Data (implemented):**
- DhanHQ REST API (Data API v2) - daily historical candles and instrument master.
  - Base URL: `https://api.dhan.co/v2` (`BASE_URL` in `backend/app/market/dhan/client.py`)
  - Endpoints used:
    - `POST /v2/charts/historical` - EOD candles via `DhanClient.daily_bars()` in `backend/app/market/dhan/client.py`
    - `GET https://api.dhan.co/v2/instrument/NSE_EQ` - NSE equity instrument list, resolved to security IDs at startup in `backend/app/market/dhan/instruments.py` (`NSE_EQUITY_URL`)
  - SDK/Client: none. Direct `httpx.AsyncClient` (`backend/app/market/dhan/client.py`).
  - Auth: header `access-token` plus header `client-id`, both set from `Credentials` (`backend/app/market/dhan/client.py`). Token from env `DHAN_ACESS_TOKEN`.
  - Rate limit: 5 requests per second; the client enforces a 0.2 s gap (`MIN_REQUEST_GAP`). Error codes are mapped in `backend/app/market/dhan/client.py`: auth codes `DH-901`, `DH-902`, `806`-`810` -> `AuthenticationError`; rate limit `DH-904`, `805` -> `RateLimitError`; no data `DH-907` -> empty result.
  - Timeout: 15 s.

- DhanHQ Live Market Feed (WebSocket) - real-time NSE equity prices.
  - URL: `wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2` (`FEED_URL` in `backend/app/market/dhan/feed.py`)
  - Client library: `websockets` 17.3 (`backend/app/market/dhan/feed.py`)
  - Binary packet decoding: `backend/app/market/dhan/packets.py` (uses `struct`)
  - Behavior: one connection; subscriptions in batches of 100 instruments; Previous Close packet gives day-change baseline; prices stamped with receive time; reconnects with backoff and resubscribes; authentication failure stops retries and marks the source unhealthy (`DhanDataSource.healthy()`, to be reported from `/api/health`).
  - Subscribed set: union of watchlist and held tickers, managed by the caller via `add_ticker` / `remove_ticker`.
  - Ticker resolution: `backend/app/market/dhan/instruments.py` (`InstrumentResolver`). Unknown symbols raise `UnsupportedTickerError` (`backend/app/market/errors.py`).

- DhanHQ access token (JWT) - credential for both Dhan endpoints above.
  - Env: `DHAN_ACESS_TOKEN` (misspelled name per spec; `DHAN_ACCESS_TOKEN` also accepted), optional `DHAN_CLIENT_ID` override.
  - Parsed without signature verification: `backend/app/market/dhan/auth.py` base64-decodes the payload, reads `exp` and `dhanClientId`, and rejects expired or malformed tokens with `AuthenticationError`.
  - Lifetime: 24 hours; not renewed automatically. Requires the Dhan Data API plan.

**Simulator (in-process, no external service):**
- `backend/app/market/simulator.py` - GBM price generator, default when no Dhan token is set. Seed prices in `backend/app/market/seed_prices.py`; synthetic history in `backend/app/market/synthetic_history.py`. Optional reproducibility via `MARKET_SEED`.

**LLM Chat (planned, not yet implemented):**
- OpenRouter via LiteLLM - model `openrouter/openai/gpt-oss-120b` with Cerebras as inference provider (PLAN.md section 9). Structured JSON output for trade and watchlist actions.
  - Auth (planned): `OPENROUTER_API_KEY` env var.
  - Mock mode (planned): `LLM_MOCK=true` returns deterministic responses; the test stack sets this.
  - Client code: not yet present; no `litellm` dependency in `backend/pyproject.toml`.

**Developer tooling:**
- Claude Code GitHub Action (`anthropics/claude-code-action@v1`) in `.github/workflows/claude.yml` and `.github/workflows/claude-code-review.yml`. Uses secret `CLAUDE_CODE_OAUTH_TOKEN`.

## Data Storage

**Databases:**
- SQLite (planned, not yet implemented)
  - Connection: file `finally.db` in the Docker named volume `finally-data`, mounted at `/app/db` (PLAN.md sections 3, 7, 11).
  - Client: not chosen yet; `backend/db/` (schema, seed, lazy init) does not exist. Stdlib `sqlite3` is the likely default given "zero config" in PLAN.md section 1, but this is not decided in the code.
  - Tables planned: `users_profile`, `watchlist`, `positions`, `trades`, `portfolio_snapshots`, `chat_messages` (PLAN.md section 7).

**File Storage:**
- Local filesystem only. No cloud object storage.

**Caching:**
- In-memory price cache: `PriceCache` in `backend/app/market/cache.py`. Holds latest price, previous price, previous close, and timestamp per ticker. Shared by the market source and the SSE stream. No Redis or external cache.

## Authentication & Identity

**Auth Provider:**
- None for end users. PLAN.md section 2 specifies no login or signup; the app is single-user with `user_id = "default"`.
- Upstream authentication: Dhan access token (see above) for market data only.
- LLM: OpenRouter API key (planned).

## Monitoring & Observability

**Error Tracking:**
- None detected.

**Logs:**
- Standard library `logging` is imported in the market package; no log aggregation service is configured. Console output is the only sink.

**Health:**
- `GET /api/health` is specified (PLAN.md section 8) but not yet implemented. It should report `source.healthy()` from `DhanDataSource`.

## CI/CD & Deployment

**Hosting:**
- Not deployed yet. Target: any container platform. AWS App Runner, Render, or similar (PLAN.md section 11). Optional Terraform under `deploy/` is a stretch goal and does not exist.

**CI Pipeline:**
- GitHub Actions for Claude Code only: `.github/workflows/claude.yml` and `.github/workflows/claude-code-review.yml`. No automated test, lint, or Docker build workflow is present.

## Environment Configuration

**Required env vars (per PLAN.md section 5):**
- `OPENROUTER_API_KEY` - required when `LLM_MOCK=false` (planned use).
- `LLM_MOCK` - `true` for deterministic LLM responses; default `false` (planned use).

**Optional env vars (in use now):**
- `DHAN_ACESS_TOKEN` - enables live NSE data; absent or empty selects the simulator.
- `DHAN_CLIENT_ID` - overrides the token's client ID.
- `MARKET_SEED` - integer seed for the simulator.

**Secrets location:**
- `.env` at the project root (gitignored; `.env.example` is committed with placeholder values). Passed to Docker via `--env-file` in the planned run scripts. Contents are intentionally not recorded in this document.

## Webhooks & Callbacks

**Incoming:**
- None. The app exposes no webhook endpoints.

**Outgoing:**
- None. Dhan is consumed via outbound WebSocket and REST calls, not webhooks.

---

*Integration audit: 2026-10-27*
