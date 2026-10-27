# FinAlly - Team Contract

Shared contract for the agent team that builds the rest of FinAlly. Product spec: [PLAN.md](PLAN.md). Market data is done (`backend/app/market/`, PLAN.md section 13). This file defines who owns what, the module boundaries, the API shapes, and how issues flow. Agents coordinate through files in `planning/`.

## 1. Team and ownership

Only the owner edits files in their area. To change something outside your area, message the owner (SendMessage) with the exact change you need.

| Member | Owns | Also writes unit tests in |
|---|---|---|
| `database-engineer` | `backend/db/` (schema, seed, lazy init, repository functions) | `backend/tests/db/` |
| `backend-api-engineer` | `backend/app/main.py`, `backend/app/state.py`, `backend/app/api/` (portfolio, watchlist, health routes), `backend/app/services/` (trading, portfolio view, watchlist, snapshots, errors) | `backend/tests/api/`, `backend/tests/services/` |
| `llm-engineer` | `backend/app/llm/`, `backend/app/api/chat.py` | `backend/tests/llm/` |
| `frontend-engineer` | `frontend/` | `frontend/` (Vitest + React Testing Library) |
| `devops-engineer` | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `test/docker-compose.test.yml`, `scripts/`, `.gitignore` | container smoke checks |
| `integration-tester` | `test/` (Playwright E2E), `planning/ISSUES.md` | the E2E suite itself |
| Lead (Claude) | `planning/TEAM_CONTRACT.md`, `planning/PLAN.md` section 13, `Tasktrackr.md`, `Docs/`, `backend/pyproject.toml` review | reviews and merges |

Shared rules:
- No git commits or pushes by any member. The lead commits when the user asks.
- Keep code short: small modules and functions, clear names, docstrings only where they help. No defensive code for cases that cannot happen.
- Use `uv` for every Python command (`uv run`, `uv add`). Never `pip` or bare `python`.
- Use the latest library APIs as of today (2026-10-27).
- Never print or copy secrets. `.env` holds a real OpenRouter key and a Dhan token. Do not echo them.
- Do not change a contract in this file without the lead's approval. If a contract is wrong, say so to the lead.

## 2. Runtime configuration

| Variable | Default | Meaning |
|---|---|---|
| `DHAN_ACESS_TOKEN` | empty | Empty means the simulator. Set means live Dhan data (PLAN.md section 5). |
| `MARKET_SEED` | unset | Integer, makes the simulator reproducible. |
| `LLM_MOCK` | `false` | `true` returns the fixed mock reply (section 7). |
| `OPENROUTER_API_KEY` | from `.env` | Needed when `LLM_MOCK=false`. |
| `FINALLY_DB_PATH` | `db/finally.db` | SQLite file, relative to the backend working directory. Docker sets `/app/db/finally.db`. |
| `FINALLY_STATIC_DIR` | `../frontend/out` | Next.js static export. Docker sets `/app/static`. The static mount is skipped when the directory does not exist. |

The backend never reads `.env` itself. Local runs use `uv run --env-file ../.env ...`. Docker uses `--env-file`. **E2E runs never load `.env`**: they set `DHAN_ACESS_TOKEN=` (empty), `MARKET_SEED=42`, `LLM_MOCK=true` explicitly, so the tests run on the simulator with the mock LLM.

## 3. Docker layout (resolves the `/app/db` clash)

The named volume is mounted at `/app/db`, so the code cannot live there. Image layout:
- `/app/backend` = backend code, including `backend/db/` schema code. Working directory for `uvicorn`.
- `/app/static` = frontend export.
- `/app/db` = named volume `finally-data`, holds `finally.db`.

## 4. Backend module contracts

### 4.1 Market (done, do not change)

`from app.market import DEFAULT_WATCHLIST, PriceCache, create_market_source, create_stream_router`. Source contract: `start`, `stop`, `add_ticker` (raises `UnsupportedTickerError`), `remove_ticker`, `get_tickers`, `daily_bars`, `healthy`. Trades price from `cache.get_price(ticker)`; `None` means the trade is rejected.

### 4.2 Application state (`backend/app/state.py`, backend-api-engineer)

```python
@dataclass
class AppState:
    cache: PriceCache
    source: MarketDataSource
```

The `PriceCache` is created at module level in `app/main.py`, because `create_stream_router(cache)` needs it when the router is built at import time. The lifespan creates the source and the `AppState`, and stores it on `app.state.app_state`. Services take `state: AppState` as their first argument. Routes get it through a dependency.

`execute_trade` rejects `quantity <= 0`, because the LLM path can pass any quantity.

Priced set (the caller owns it): watchlist plus held tickers. Call `source.add_ticker` when a ticker is watched or first bought. Call `source.remove_ticker` when it is neither watched nor held. At startup, call `source.start(watchlist + held)`.

### 4.3 Database (`backend/db/`, database-engineer)

- `connection.py`: `db_path() -> Path`, `connect() -> sqlite3.Connection` (`row_factory = sqlite3.Row`, foreign keys on), `init_db() -> None` (idempotent: creates tables and seeds when missing), `transaction()` context manager yielding a connection that commits on success and rolls back on error.
- `models.py`: frozen dataclasses `Position(ticker, quantity, avg_cost, updated_at)`, `Trade(id, ticker, side, quantity, price, executed_at)`, `WatchlistEntry(ticker, added_at)`, `Snapshot(total_value, recorded_at)`, `ChatMessage(role, content, actions, created_at)`. `actions` is a decoded `list[dict] | None`.
- Repository functions. The first argument is always `conn`, so services can group writes in one transaction:
  - `get_cash_balance(conn) -> float`, `set_cash_balance(conn, amount) -> None`
  - `list_positions(conn) -> list[Position]`, `get_position(conn, ticker) -> Position | None`, `save_position(conn, ticker, quantity, avg_cost) -> None` (upsert), `delete_position(conn, ticker) -> None`
  - `insert_trade(conn, ticker, side, quantity, price) -> Trade`, `list_trades(conn) -> list[Trade]`
  - `list_watchlist(conn) -> list[WatchlistEntry]`, `add_watchlist(conn, ticker) -> bool` (False if already present), `delete_watchlist(conn, ticker) -> bool` (False if absent)
  - `insert_snapshot(conn, total_value) -> None`, `list_snapshots(conn, limit: int | None) -> list[Snapshot]` (oldest first; `limit` keeps the newest N)
  - `insert_chat_message(conn, role, content, actions) -> None`, `list_chat_messages(conn) -> list[ChatMessage]` (oldest first)
- Schema: PLAN.md section 7, exact table and column names. `user_id` defaults to `"default"` everywhere; repository code uses the constant `DEFAULT_USER_ID`. Timestamps are ISO-8601 UTC strings.
- Seed: profile with `cash_balance = 1000000.0`, and the ten `DEFAULT_WATCHLIST` entries.
- Schema SQL lives in `backend/db/schema.sql` (read by `init_db`).
- The DB file is `FINALLY_DB_PATH`. Tests point it at a tmp path.

### 4.4 Services (`backend/app/services/`, backend-api-engineer)

- `errors.py`: `ServiceError(Exception)` with `status_code` and `message`. Subclasses: `RejectedError` (400: bad ticker, insufficient cash or shares, duplicate), `NotFoundError` (404), `PriceUnavailableError` (503: no price yet). The LLM layer catches `ServiceError` and appends the message to the chat reply.
- `trading.py`: `execute_trade(state, ticker, quantity, side) -> Trade`. Uses `state.cache.get_price` only. Buy: needs cash for `quantity * price`; weighted-average `avg_cost`. Sell: needs held quantity; `avg_cost` unchanged; delete the position when quantity reaches zero. Writes cash, position and trade in one `transaction()`. Adds the ticker to the priced set if needed. Records a snapshot right after commit.
- `portfolio.py`: `build_portfolio(state) -> PortfolioView` with `cash_balance`, `total_value` (cash plus market values), `unrealized_pnl`, and `positions` (ticker, quantity, avg_cost, current_price, market_value, unrealized_pnl, unrealized_pnl_percent, day_change_percent). Current price falls back to `avg_cost` only when the ticker has no price yet. The LLM reuses this view for its context.
- `watchlist.py`: `list_watchlist(state) -> list[WatchlistView]` (ticker, added_at, price or null, previous_close, day_change_percent); `add_to_watchlist(state, ticker) -> WatchlistEntry` (normalise to upper case; `RejectedError` if the source rejects the ticker or it is a duplicate); `remove_from_watchlist(state, ticker)` (`NotFoundError` if absent).
- `snapshots.py`: `record_snapshot(state) -> None` (total value into the DB); `snapshot_loop(state)` runs every 30 s as a background task. The lifespan records one snapshot at startup.

### 4.5 Routes (`backend/app/api/`)

Routes that only read the database or the cache are `def` (sync). Routes that await the market source (watchlist POST and DELETE, trade POST, chat) are `async def`, because `source.add_ticker`, `source.remove_ticker` and the LLM call are async. Sync `sqlite3` calls in async routes are fast enough at this scale. Errors: one exception handler in `main.py` turns `ServiceError` into a `JSONResponse` with its `status_code` and the body `{"detail": "..."}`. Routes never raise `HTTPException` for service errors.

Dependencies: the state dependency is `StateDep` from `app.api.deps`.

## 5. HTTP API contract

Base path `/api`. Money is INR (₹). JSON numbers are plain floats.

### 5.1 Health

`GET /api/health` returns 200:
```json
{"status": "ok", "market_source": "dhan", "market_healthy": true}
```
`market_source` is `"dhan"` or `"simulator"`. `market_healthy` is `source.healthy()`. Always 200; the status reflects the server being up.

### 5.2 Prices (SSE)

`GET /api/stream/prices` (already implemented). Event `data:` is a JSON object keyed by ticker. Each value has `ticker, price, previous_price, previous_close, timestamp, change, direction, day_change, day_change_percent`. `direction` is `up`, `down` or `flat`. `timestamp` is Unix epoch seconds (a float), not ISO. Events are sent only when prices changed. `retry: 1000` is sent first. The stream covers the priced set.

### 5.3 Portfolio

`unrealized_pnl_percent` is `unrealized_pnl / (quantity * avg_cost) * 100`, the P&L as a share of cost basis.

`GET /api/portfolio` returns 200:
```json
{
  "cash_balance": 1000000.0,
  "total_value": 1000000.0,
  "unrealized_pnl": 0.0,
  "positions": [
    {"ticker": "TCS", "quantity": 10, "avg_cost": 2500.0, "current_price": 2529.0,
     "market_value": 25290.0, "unrealized_pnl": 290.0, "unrealized_pnl_percent": 1.16,
     "day_change_percent": 0.4}
  ]
}
```

`POST /api/portfolio/trade` with body `{"ticker": "TCS", "quantity": 10, "side": "buy"}` (`side` is `buy` or `sell`, `quantity > 0`). Returns 200:
```json
{"trade": {"id": "...", "ticker": "TCS", "side": "buy", "quantity": 10, "price": 2529.0, "executed_at": "..."},
 "portfolio": { ...same shape as GET /api/portfolio... }}
```
Schema errors give 422. Business rejections give 400 (insufficient cash or shares, unknown ticker). No price yet gives 503.

`GET /api/portfolio/history?limit=N` returns 200 `[{"total_value": 1000000.0, "recorded_at": "..."}]`, oldest first. `limit` is optional; without it, all snapshots are returned.

### 5.4 Watchlist

`GET /api/watchlist` returns 200 `[{"ticker": "TCS", "added_at": "...", "price": 2529.0, "previous_close": 2529.0, "day_change_percent": 0.0}]`. `price` and the other price fields are `null` until the ticker is priced.

`POST /api/watchlist` with `{"ticker": "WIPRO"}` returns 201 `{"ticker": "WIPRO", "added_at": "..."}`. Duplicate gives 400. Unsupported (Dhan only) gives 400.

`DELETE /api/watchlist/{ticker}` returns 204. Absent gives 404.

### 5.5 Chat

`POST /api/chat` with `{"message": "..."}` returns 200:
```json
{"message": "Bought 1 TCS.",
 "trades": [{"ticker": "TCS", "quantity": 1, "side": "buy", "price": 2529.0}],
 "watchlist_changes": null}
```
`trades` is the list of executed trades, or `null`. `watchlist_changes` is the list of applied `{"ticker", "action"}` objects, or `null`. Trade or watchlist failures are appended to `message`. If the LLM call fails or returns invalid output, the response is 502 and nothing is stored.

`GET /api/chat/history` returns 200 `[{"role": "user", "content": "...", "actions": null, "created_at": "..."}]`, oldest first. For an assistant message, `actions` is the same object as the POST reply's `trades` and `watchlist_changes`: `{"trades": [...] | null, "watchlist_changes": [...] | null}`, or `null` when nothing ran. User messages always have `actions: null`. This endpoint is an addition to PLAN.md so the UI can show history after a reload.

## 6. Frontend contract (frontend-engineer)

- Static export (`output: 'export'`) to `frontend/out/`. All calls are same-origin: `/api/*`. No CORS.
- Prices come from one `EventSource('/api/stream/prices')`. The connection indicator is green (`open`), yellow (reconnecting), or red (closed). Watchlist membership comes from `GET /api/watchlist`; prices come from the stream.
- Sparklines build from the SSE stream since page load. No history endpoint for prices.
- Portfolio, positions, and history come from the REST endpoints. Refresh after every trade and chat reply.
- Colours and layout are PLAN.md section 2 (dark `#0d1117`, accent `#ecad0a`, blue `#209dd7`, purple `#753991` submit buttons, buy blue, sell yellow, green and red only for P&L). INR is shown as `₹` with Indian grouping (`Intl.NumberFormat('en-IN')`).
- Main sections (PLAN.md section 10): watchlist, main chart, portfolio heatmap (treemap with a cash tile), P&L line chart, positions table, trade bar, AI chat panel (docked, collapsible), header (total value, connection dot, cash).
- Test hooks for Playwright. These names are the contract; the specs in `test/e2e/` use exactly these.

| `data-testid` | Element | Attributes |
|---|---|---|
| `connection-status` | header dot | `data-state`: `open`, `reconnecting`, `closed` |
| `header-cash` | cash balance in header | text in INR |
| `watchlist-row` | one watchlist row | `data-ticker` |
| `watchlist-price` | price cell inside a row | `data-price` (number, updated on each tick) |
| `watchlist-remove` | remove button inside a row | |
| `watchlist-add-input` | ticker input for adding | |
| `watchlist-add-button` | add button | |
| `position-row` | one positions-table row | `data-ticker` |
| `position-quantity` | quantity cell inside a position row | |
| `trade-ticker` | trade bar ticker input | |
| `trade-quantity` | trade bar quantity input | |
| `trade-buy` | buy button | |
| `trade-sell` | sell button | |
| `heatmap-tile` | one treemap tile (positions and the cash tile) | `data-ticker` (`CASH` for cash), `data-pnl`: `gain`, `loss` or `flat` |
| `pnl-chart` | P&L chart container | `data-point-count` (number of points) |
| `chat-input` | chat message input | |
| `chat-send` | chat send button | |
| `chat-message` | one chat message | `data-role`: `user` or `assistant` |
| `chat-trade` | inline trade confirmation in chat | text includes side, quantity and ticker |
| `chat-loading` | loading indicator while the LLM replies | (not asserted yet) |
| `load-error` | banner shown when the account data fails to load; cleared on the next good load | (not asserted yet) |
| `header-total-value` | total portfolio value text in header | (not asserted yet) |

Sections (not asserted yet, but every section carries one so debugging is easy):

| `data-testid` | Section | Attributes |
|---|---|---|
| `header` | page header | |
| `watchlist-panel` | watchlist | |
| `main-chart` | selected-ticker chart | `data-ticker` (the selected ticker) |
| `heatmap` | portfolio treemap | |
| `pnl-chart` | P&L line chart | `data-point-count` (number of points); asserted |
| `positions-table` | positions table | |
| `trade-bar` | trade bar | |
| `chat-panel` | AI chat panel | |

Other contract points the specs rely on: `GET /api/health` is the webServer readiness URL; `POST /api/portfolio/trade` returns `trade.price`; `GET /api/portfolio` returns `positions[].ticker` and `quantity`. The `data-price` and `data-point-count` attributes are read as strings and parsed as numbers.
- Components and modules stay short, with unit tests in Vitest.

## 7. LLM contract (llm-engineer)

- Model `openrouter/openai/gpt-oss-120b` with the Cerebras provider, via LiteLLM. Follow `.claude/skills/cerebras-inference/SKILL.md` exactly. Structured output is a pydantic model.
- Output schema: `LLMReply(message: str, trades: list[LLMTrade] = [], watchlist_changes: list[LLMWatchlistChange] = [])`, with `LLMTrade(ticker, quantity, side)` and `LLMWatchlistChange(ticker, action)` where `action` is `add` or `remove`.
- Flow (PLAN.md section 9): load portfolio view, watchlist, and full chat history; build the prompt; call the LLM; parse; store the user message; execute trades through `execute_trade` and watchlist changes through the services; catch `ServiceError` and append it to `message`; store the assistant message with its `actions`; return the response shape of section 5.5. Failed trades do not call the LLM again.
- `LLM_MOCK=true`: no network call. Returns a fixed reply whose trade is `{"ticker": "TCS", "quantity": 1, "side": "buy"}` with message `"Bought 1 TCS (mock reply)."`. It still goes through the normal trade path, so E2E tests see real portfolio changes.
- Prompt: "FinAlly, an AI trading assistant", concise and data-driven, Indian market context (NSE, INR).
- Run LiteLLM without blocking the event loop (`acompletion` in an `async` helper, or keep the route `def`).

## 8. Test and DevOps contract

- Backend unit tests: `cd backend && uv run pytest` (existing 163 pass and must stay green). Lint: `uv run ruff check app db tests`.
- Frontend unit tests: `cd frontend && npm test`. Build: `npm run build`.
- E2E: `test/` uses `@playwright/test`. Specs follow the PLAN.md section 12 scenarios: fresh start, watchlist add and remove, buy, sell, portfolio visualisation, mocked AI chat with inline trade, SSE reconnect. Run against `BASE_URL` (default `http://localhost:8000`).
- E2E runs with `workers: 1`. All specs share one server and one temp DB. The fresh-start spec runs first (file prefix `00-`).
- Two E2E loops:
  - Local: Playwright `webServer` runs `uv run uvicorn app.main:app --port 8000` in `backend/` with the section 2 test variables, and `FINALLY_DB_PATH` set to a fresh temp file each run.
  - Container: `test/docker-compose.test.yml` runs the app image (with `LLM_MOCK=true` and `DHAN_ACESS_TOKEN=` set in the file) plus a Playwright container that talks to `http://app:8000`.
- Docker: the image is multi-stage (Node 20 slim builds `frontend/out`; Python 3.12 slim with uv installs `backend` with `--no-dev --no-group demo`). Port 8000. Named volume `finally-data` at `/app/db`. Healthcheck on `/api/health`.
- Scripts (PLAN.md section 11): `start_mac.sh`, `stop_mac.sh`, `start_windows.ps1`, `stop_windows.ps1`. Idempotent. Build on `--build` or when the image is missing. Stop removes the container and the image, never the volume. Start prints the URL and opens the browser optionally. They pass `--env-file .env` when the file exists.
- `Docker Desktop` is not running on this machine (the daemon pipe is missing). DevOps starts it before container checks. If it cannot start, DevOps reports that as a blocker and verifies everything else by reading.

## 9. Issue protocol (`planning/ISSUES.md`)

1. `integration-tester` runs the E2E suite and records each failing test as an issue in `planning/ISSUES.md`: ID, owner, repro command, expected, actual, and the failing spec. The tester names the owner by the table in section 1 and reads the root cause before assigning. An issue that belongs to two areas goes to both owners, each with a clear part.
2. The tester sends each owner a SendMessage with the issue IDs. Owners fix the root cause (proved with evidence, not a guess), add or update a unit test, and run their unit tests green.
3. The owner marks the issue `fixed` with a short note on the cause and the change, then messages the tester.
4. The tester re-runs the affected specs, then the full suite. It marks an issue `verified` only after a passing run, and then `closed`.
5. Repeat until the whole E2E suite passes on the local loop, then on the container loop. Stop and report when a blocker needs the user (for example Docker cannot start, or an API key is missing).

## 10. Definition of done

- Every area's unit tests pass and ruff is clean.
- Backend runs locally with the simulator (no token) and the mock LLM; every endpoint in section 5 responds with the documented shape.
- The E2E suite passes against the local run and against the container.
- `Docker` image builds; `scripts/start_windows.ps1` brings the app up at `http://localhost:8000` and `stop_windows.ps1` removes it.
- Lead updates PLAN.md section 13, `Docs/Readme.md`, `Docs/help.md`, and `Tasktrackr.md`, and reports to the user.
