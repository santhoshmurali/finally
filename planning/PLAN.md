# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

### Terminology

- **Watchlist tickers**: tickers the user has added to the watchlist (the 10 defaults at start).
- **Held tickers**: tickers with a non-zero position.
- **Priced tickers**: watchlist tickers plus held tickers. Only these receive live prices.
- **Trade**: a buy or sell execution. All trades are market orders, so "order" is not used.
- **Simulator**: the built-in price generator, used when no Dhan token is set.
- **Dhan**: the DhanHQ live data source for Indian markets (NSE equities, INR), over its WebSocket Live Market Feed (see §5, §6). All prices are in INR (₹).

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). The user opens `http://localhost:8000` in a browser (the start script can optionally open it automatically). No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- ₹10,00,000 (₹1,000,000) in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, % change (vs. previous close)
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: background `#0d1117`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)
- Buy button: Blue Primary; Sell button: Accent Yellow. Green/red stay reserved for P&L.

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (named volume)                 │
│  Background task: market data polling/simulator │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, file `finally.db` in the named Docker volume `finally-data`, mounted at `/app/db` for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, live NSE data via the DhanHQ WebSocket feed if a Dhan access token is provided

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; docker-compose is optional for running the app but required for the E2E test stack; no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   ├── app/market/           # Market data (built): Dhan feed, simulator, SSE stream
│   ├── demo/                 # Console demo: uv run python -m demo
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── Dockerfile                # Multi-stage build (Node → Python)
├── docker-compose.yml        # Optional convenience wrapper
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions, seed logic, and migration logic. The backend initializes the database on startup and again on first request, creating tables and seeding default data only when they are missing.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required when LLM_MOCK=false: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: DhanHQ access token (JWT, valid 24 h) for live NSE market data. Needs the Dhan Data API plan.
# The client ID is read from the token. If not set, the built-in market simulator is used.
DHAN_ACESS_TOKEN=

# Optional: overrides the client ID inside the token
# DHAN_CLIENT_ID=

# Optional: integer seed that makes the simulator reproducible
# MARKET_SEED=

# Optional: Set to "true" for deterministic mock LLM responses (testing); the OpenRouter key is not needed when true
LLM_MOCK=false
```

### Behavior

- If `DHAN_ACESS_TOKEN` is set and non-empty → backend streams live NSE prices from DhanHQ (`DHAN_ACCESS_TOKEN` is accepted too; surrounding quotes are stripped). An expired or malformed token stops startup with a clear error rather than silently simulating
- If `DHAN_ACESS_TOKEN` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses in the same structured schema as the real LLM (see §9 LLM Mock Mode)
- The test stack sets `LLM_MOCK=true`; the application default remains `false`
- The backend reads `.env` from the project root (mounted into the container or read via docker `--env-file`)
- This variable list is provisional and will be finalized during development (compare with `.env.example`)

---

## 6. Market Data

Detailed design: [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md); API: [MARKET_INTERFACE.md](MARKET_INTERFACE.md); provider notes: [DHANHQ_API.md](DHANHQ_API.md); simulator: [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md). **Implemented and tested** (see §13).

Scope is **Indian markets only**: NSE cash equities priced in INR. US stocks are not supported.

### Two Implementations, One Interface

Both the simulator and the Dhan source implement the same abstract interface (`MarketDataSource`). The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., IT stocks move together, banks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic NSE seed prices in INR (e.g., TCS ~₹2,529, RELIANCE ~₹1,209)
- Simulates a daily close: the previous close is set from the seed price at startup, and all % change figures are measured against it
- Runs as an in-process background task — no external dependencies

### Dhan Live Feed (Optional)

- Uses the DhanHQ **Live Market Feed WebSocket** (push, not polling): one connection, ticker subscriptions in batches of 100 instruments
- Tickers are NSE equity symbols resolved to Dhan security IDs from Dhan's public instrument list at startup; an unknown symbol is rejected (`UnsupportedTickerError`)
- On subscribe Dhan sends each ticker's last price and its previous close immediately (also when the market is closed), then pushes a price on every change
- Day change is measured against the **Previous Close packet** from the feed
- Prices are stamped with receive time (Dhan's trade-time field is unreliable)
- Reconnects automatically with backoff and resubscribes; an authentication failure (expired token, no Data plan) stops retrying and marks the source unhealthy for `/api/health`
- Daily history (EOD candles) via Dhan's REST history endpoint
- Subscribes the union of watchlist tickers and held tickers (priced tickers); the caller adds and removes tickers at runtime

### Shared Price Cache

- A single background task (simulator or Dhan feed) writes to an in-memory price cache
- The cache holds the latest price, previous price (prior tick), previous close (prior session), and timestamp for each ticker
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- Each tick (~500ms), the server sends one SSE event containing the latest data for every priced ticker (watchlist plus held tickers)
- For each ticker in the event: ticker, price, previous price, previous close, timestamp, change direction, day change and day change percent
- Client handles reconnection automatically (EventSource has built-in retry)

---

## 7. Database

### SQLite with Lazy Initialization

The backend initializes the database on startup and again on the first request. It creates the schema and seeds default data only when the file or tables are missing. This means:

- Migrations run automatically from `backend/db/`; no manual migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically

### Schema

All tables include a `user_id` column defaulting to `"default"`. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `user_id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `1000000.0`, INR)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user; the row is deleted when a sell brings quantity to zero)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL (weighted average cost on buys; unchanged on sells)
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded every 30 seconds by a background task, and immediately after each trade execution.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — trades executed, watchlist changes made; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `user_id="default"`, `cash_balance=1000000.0` (₹10,00,000)
- Ten watchlist entries (NSE): RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, LT, HINDUNILVR

---

## 8. API Endpoints

_Request/response schemas and status codes are to be detailed during implementation._

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart); optional range/limit query parameters, all snapshots returned when omitted |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}`; duplicate or unsupported tickers are rejected |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive the complete JSON response: `message` (always present), `trades` (executed trades, or null), `watchlist_changes` (applied changes, or null) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use the cerebras skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads the entire conversation history for the user from the `chat_messages` table
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras skill
5. Parses the complete structured JSON response
6. Auto-executes any trades or watchlist changes specified in the response
7. Stores the message and executed actions in `chat_messages`
8. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "TCS", "quantity": 10, "side": "buy"}
  ],
  "watchlist_changes": [
    {"ticker": "WIPRO", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute, using the `{ticker, quantity, side}` shape from §8. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells)
- `watchlist_changes` (optional): Array of `{ticker, action}` objects, where `action` is `"add"` or `"remove"`

In the chat response returned to the frontend, `trades` is populated when trades were executed and null otherwise; `watchlist_changes` is populated when the watchlist changed and null otherwise. Both can be populated in the same reply.

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade fails validation (e.g., insufficient cash), the backend appends the error text to the `message` field of the chat response. The LLM is not called again.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. The mock responses use the same structured schema as the real LLM, so the rest of the flow is unchanged. Every mock chat response includes the same fixed trade. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watchlist tickers with: ticker symbol, current price (flashing green/red on change), % change vs. previous close, and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by weight (share of total portfolio value, including cash), colored by P&L (green = profit, red = loss). Cash appears as its own tile.
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, % change
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Canvas-based charting library preferred (Lightweight Charts or Recharts) for performance
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

_The location of the `static/` directory is to be decided._

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The named volume `finally-data` is mounted at `/app/db` in the container. The backend writes `finally.db` to this path.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container and its Docker image
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows, with the same behavior as the macOS scripts (the stop script also removes the image).

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Dhan packet decoding, feed reconnect and REST error mapping work (against fakes), both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow
- API routes: correct status codes, response shapes, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: The test stack (`test/docker-compose.test.yml`) sets `LLM_MOCK=true` for speed and determinism. The application default remains `false`.

**Key Scenarios**:
- Fresh start: default watchlist appears, ₹10,00,000 balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive a response, trade execution appears inline
- SSE resilience: disconnect and verify reconnection

_Expected colors, status codes, and response shapes are to be specified during implementation (see §8)._

---

## 13. Implementation Status

_Last updated 2026-11-02. Update this table whenever a component changes state._

| Component | Status | Where | Evidence |
|---|---|---|---|
| Market data: unified interface, price cache, errors | **Done** | `backend/app/market/` | 125 market data unit tests, 100% line coverage of `app/` (226 backend tests in total as of 2026-11-02, including the demo) |
| Market data: simulator (GBM, correlation, events, synthetic history) | **Done** | `simulator.py`, `seed_prices.py`, `synthetic_history.py` | unit tests incl. statistical checks; ran under uvicorn |
| Market data: Dhan live source (WebSocket feed, instrument resolver, REST history) | **Done** | `backend/app/market/dhan/` | unit tests with a scripted fake socket; verified against the real service with a real token, after hours and during market hours (DHANHQ_API.md section 9) |
| Market data: SSE endpoint `GET /api/stream/prices` | **Done** | `stream.py` | unit tests; streamed from uvicorn with Dhan data and with the simulator |
| Console demo (`uv run python -m demo`): live table and per-symbol line charts, add/remove symbols | **Done** | `backend/demo/` | 38 unit tests incl. typed-input run of the real app; headless run against live Dhan |
| Market data docs | **Done** | `planning/DHANHQ_API.md`, `MARKET_DATA_DESIGN.md`, `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md` | rewritten to match the code |
| Database (SQLite schema, seed, lazy init) | **Done** | `backend/db/` | 5 tests: schema, seeding once, rollback on error |
| Portfolio and trade service, watchlist service, snapshots task | **Done** | `backend/app/portfolio.py`, `watchlist.py`, `snapshots.py` | 22 + 10 tests: fills, weighted cost, sells, rejections, priced-set rules, history |
| `/api/health` (reports `source.healthy()`) | **Done** | `backend/app/api/system.py` | API test; smoke-tested under uvicorn and in the container |
| LLM chat integration and mock mode | **Done** | `backend/app/chat.py`, `backend/app/llm/` | 10 tests incl. patched LiteLLM client; live Cerebras reply and trade verified in the browser |
| FastAPI app wiring (lifespan, static files) | **Done** | `backend/app/main.py`, `backend/app/api/` | 14 API tests; static frontend served from one port |
| Frontend (Next.js) | **Done** | `frontend/` | 39 Vitest tests; lint and typecheck clean; verified in Playwright |
| Dockerfile, start/stop scripts | **Done** | `Dockerfile`, `docker-compose.yml`, `scripts/` | image built; container healthy; `/api/health` and chat verified |
| Playwright E2E tests | **Done** | `test/tests/`, `test/live/` | 7 scenarios passing in `test/docker-compose.test.yml` (mock LLM, simulator); 30 live scenarios passing in market hours against the real account |
| Functional scenarios | **Done** | `test/functional/scenarios.mjs` | 13 live scenarios passing (buy, sell, averaging, fractions, rejections, snapshots, watchlist, chat) |

### Market data: contract for the next components

- Create the source once in the FastAPI lifespan: `cache = PriceCache(); source = create_market_source(cache); await source.start(initial_priced_tickers)`; `await source.stop()` on shutdown; mount `create_stream_router(cache)`.
- The **caller owns the priced set**: call `add_ticker` when a ticker is watched or first bought and `remove_ticker` when it is neither watched nor held. Map `UnsupportedTickerError` to a 4xx for `POST /api/watchlist` and for trades.
- Trades price from `cache.get_price(ticker)` only; `None` means "not priced yet" and the trade is rejected.
- Report `source.healthy()` from `/api/health`.
- Starting cash and the default watchlist changed from the original US spec to INR and NSE tickers (§2, §7); `DEFAULT_WATCHLIST` in `app.market` is the single source for the ten tickers.

### Known limits and open items

- Dhan was observed during market hours for 6 minutes only (about 1 tick/s per busy ticker, stable connection, no reconnects). Market-hours sessions on 2026-11-02 are recorded in the live verification log below. A complete trading day is still unobserved (DHANHQ_API.md section 11).
- Dhan tokens last 24 hours and are not renewed automatically; an expired token makes the source unhealthy until a new token is configured and the app restarted (MARKET_DATA_DESIGN.md section 6).
- The simulator has no market calendar or holiday awareness.
- The console demo's full-screen view needs a real Windows console (PowerShell, cmd, Windows Terminal); it was verified through typed-input tests and a headless run against live Dhan data, not by eye on every terminal. `prompt-toolkit` is a default dependency group, so the production image must be built without the `dev` and `demo` groups.


### Deviations from this specification

Recorded 2026-10-27 after the full build. The code follows the current behaviour listed here; the spec text above is unchanged.

- **SSE cadence (section 6).** The stream sends one event whenever the price cache changes, not one every ~500 ms. With a live feed outside market hours, nothing is sent until a price moves.
- **Health status (section 8).** `GET /api/health` returns HTTP 200 in all cases. `"status"` is `"ok"` when the market source is healthy and `"degraded"` when it is not. Callers must read the body, not the status code.
- **Chat history (sections 7 and 9).** Turns are stored in `chat_messages`, but there is no endpoint to read them back. The frontend keeps the visible conversation in memory, so a page refresh clears it.
- **Simulator symbols (section 6).** The simulator accepts any symbol matching `^[A-Z0-9][A-Z0-9&.\-]{0,19}$` and prices it deterministically. Dhan still rejects anything that is not an NSE equity. A trade or watchlist add on an unknown symbol therefore succeeds in simulator mode and fails in Dhan mode.
- **Snapshot on startup (section 7).** The app records one portfolio snapshot when it starts, in addition to the 30-second and post-trade snapshots.
- **Portfolio history query (section 8).** `range` accepts `1h`, `1d`, `7d` or `all` (default `all`), and `limit` returns the newest N rows, oldest first.
- **Watchlist status codes (section 8).** Adding a ticker that is already watched returns 409; removing one that is not watched returns 404; unknown or malformed symbols return 400. Chat errors from the model return 503.
- **Treemap (section 10).** The heatmap is a small squarified SVG layout written in the frontend, not a charting library.
- **Backend layout (section 4).** Services and routes live under `backend/app/` as `portfolio.py`, `watchlist.py`, `chat.py`, `repository.py`, `api/` and `llm/`. The spec leaves the internal structure to the implementing agents.
- **First buy on an unwatched ticker (sections 6 and 8).** The trade waits up to 5 seconds for the first price after subscribing. It is rejected only if no price arrives in that time, and the subscription is then released. The spec only says the trade is rejected when there is no price.
- **Chat auto-execution (section 9).** Kept as specified, by decision on 2026-11-02, after a chat message sold every holding at once. Bulk actions have no confirmation step. Revisit this if the app is used with real money.
- **Stop scripts (section 11).** `scripts/stop_windows.ps1` also removes unused images labelled `app=finally` that earlier rebuilds left behind. `scripts/stop_mac.sh` does not yet do this.
- **Test layout (sections 4 and 12).** `test/` also contains `functional/` (scenario runner against any backend) and `live/` (browser suite for the live feed and the real account). The Playwright service in `test/docker-compose.test.yml` shares the app container network and reaches the app at `localhost:8000`, because the browser could not reach the app by service name.

### Live market verification log

Run against the Dhan live feed through `scripts/start_windows.ps1` (the `.env` is passed to Docker, not read by the scripts). Log timestamps in this section are UTC; IST is UTC+5:30. Correction: the first entries below were recorded as "pre-open" but ran during market hours (12:28 to 12:32 IST).

**2026-11-02, market hours (12:28 to 12:32 IST)**

| Check | Result |
|---|---|
| `/api/health` reports the live source | Pass: `market_source: dhan`, healthy |
| Prices and day change arrive after start | Pass: all watchlist tickers priced within about 10 s |
| Stream rate, 30 s sample | 60 events (about 2 per second) |
| Non-NSE symbol (`NOPE`) rejected | Pass: 400, "NOPE is not an NSE equity" |
| Valid NSE symbol outside defaults (`WIPRO`) added and priced | Pass: 201, then priced; removed afterwards (204) |
| Buy and sell at live price (`RELIANCE`, 1 share) | Pass: filled at 1254.80, cash reconciled exactly |
| Live LLM analysis grounded in the portfolio | Pass: cash and largest position matched the API |
| Live LLM trade through chat (`INFY`, 1 share) | Pass: executed at the live price, shown inline |
| Browser: connection, prices, heatmap, P&L chart, positions | Pass: connected, all 11 watchlist rows priced |

**Open items to check during the session (not yet run)**

- Stream and price behaviour from 09:15 to 15:30 IST, including tick rate and flash behaviour under real volume.
- Day change figures against the official NSE close. RELIANCE showed about +7.7% at 12:30 IST; confirm the previous-close value.
- Reconnection of the browser stream during a live session.
- Token expiry: `/api/health` should report `degraded` and the header should stop updating. Not tested; needs an expired token.
- The E2E suite assumes the simulator and a fresh database, so it is not run against live data.

**2026-11-02, functional scenarios (`test/functional/scenarios.mjs`, live Dhan feed)**

Result: 12 of 13 scenarios pass. The one failure is a defect (below), kept as a regression test.

| Area | Scenarios | Result |
|---|---|---|
| Buying and selling | Open a position at the trade price; second buy averages cost; partial sell keeps average cost; fractional quantities; full sell removes the position | Pass |
| Rejections | Overselling; buying beyond cash; zero, negative and unknown-side orders | Pass, and nothing changes after a rejection |
| Snapshots | A successful trade adds a portfolio snapshot | Pass |
| Watchlist | Duplicate (409), malformed and unsupported (400), unknown removal (404); add then remove round-trip | Pass |
| Chat | "Buy 1 share" through the live LLM executes and is reported | Pass |
| Unwatched NSE ticker | Buying a ticker not on the watchlist (WIPRO) prices it | **Fail** (defect 1) |

**Defect 1 (fixed, see the re-run below): a first buy on an unwatched ticker never gets a price.**
- A buy on an unpriced ticker calls `add_ticker`, then is rejected immediately with "not priced yet", because the first price takes about one second to arrive.
- The `finally` block in `execute_trade` then calls `release_if_unused`, which unsubscribes the ticker before that price lands.
- Each retry repeats the cycle, so the ticker can't be priced by trading alone. Three retries 1 second apart all fail.
- Adding the same ticker to the watchlist works: the price arrives in about 1 second, and a second add after a remove also gets a price. So the feed itself is fine; the trade path is the problem.
- Proposed fix (not applied, needs approval): when a buy is rejected only because the ticker is unpriced, wait up to about 5 seconds for the first price before rejecting, and keep the subscription while waiting.

**Account state change, not caused by these scenarios:** the chat audit trail (`chat_messages` and `trades` tables) shows two chat messages from 07:00 to 07:01. "sell everything" sold all eight positions in one step, and "buy ICICIBANK 30% of my capital" then bought 223 shares. The app has no login, so the source of those messages is not recorded. The scenarios' own trades netted to zero.

**Design risk:** chat trades execute immediately with no confirmation, so one ambiguous message can liquidate the portfolio. PLAN section 9 specifies auto-execution by design. This needs a decision: keep it, or require confirmation for bulk actions.

**2026-11-02, functional scenarios re-run after the fix (live, market hours)**

- Fix: `PortfolioService.execute_trade` waits up to 5 s for the first price of a ticker it has just subscribed to, before rejecting a buy. Verified by two unit tests (late first tick fills; no tick rejects and releases the subscription) and by a live WIPRO round trip.
- Result: 13 of 13 scenarios pass against the live Dhan feed, with the Docker image rebuilt and restarted. Starting cash ₹7,22,359.60; ending cash ₹7,22,358.40. The ₹1.20 difference is the net of round trips that filled at the live price at each moment, not a loss from a bug.
- Account state: the live account was used as instructed. Scenario trades net to zero shares; the holding left is ICICIBANK 223, as before the run.

### Live end-to-end suite (2026-11-02, market hours, real account)

`test/live/live.spec.ts`, run with `npm run test:live` in `test/`. Browser tests against the live Dhan feed, run in market hours. Assertions are relative, so they hold whatever the prices and holdings are. Every trade is reversed in the same test, and `afterAll` sells any leftover and removes the test watchlist entry.

**Result: 30 of 30 passed.** One earlier run failed on a locator bug in the test (Next.js adds its own `role="alert"` element); the app behaved correctly and the locator was scoped to the app's error paragraphs.

| Area | Scenarios |
|---|---|
| Market data | Connected with all tickers priced; prices move and flash; sparklines fill; day change matches backend; ticker click switches chart and trade ticker; dropped stream is reported and recovers |
| Trading | Buy fills at live price and debits cash; sell closes position and credits cash; ticker case-insensitive; fractional quantities; zero quantity refused; overselling refused; rejected order leaves cash unchanged; server error shown |
| Watchlist | Add NSE ticker, priced, remove; duplicate, non-NSE and malformed refused with reason |
| Portfolio views | Heatmap tiles per holding and cash; P&L chart rendered; positions table agrees with API |
| Assistant | Question answered and does not trade; loading indicator; buy in chat confirmed inline and reversed; watchlist changes in chat confirmed and reversed; panel hide and show; model error shown |
| Layout and persistence | No horizontal scroll at 1366 and 1024 px; holdings and watchlist survive reload; conversation clears on reload (recorded deviation) |

**Not covered by this suite:** mobile width (390 px; PLAN says desktop-first, tablet functional), token expiry, behaviour after the market closes at 15:30, and the simulator path.

**Account after the run:** holdings unchanged (ICICIBANK 223), cash ₹7,22,358.40 as before the run, no test watchlist entry left behind.
