# FinAlly - Help

FinAlly is a trading workstation for NSE stocks in INR. Prices stream live, you trade a virtual ₹10,00,000 portfolio with market orders, and an AI assistant can analyse your holdings and place trades for you.

## Run the app with Docker (recommended)

You need Docker and an OpenRouter API key.

```bash
cp .env.example .env            # then set OPENROUTER_API_KEY in .env
scripts/start_mac.sh            # macOS / Linux   (add --build to rebuild, --open to open the browser)
scripts/start_windows.ps1       # Windows PowerShell (add -Build, -Open)
```

Open http://localhost:8000. Your data lives in the Docker volume `finally-data`, so it survives restarts.

```bash
scripts/stop_mac.sh             # stop and remove the container and image (keeps the data)
scripts/stop_windows.ps1        # same, and also removes unused FinAlly images left by earlier rebuilds
```

The Windows stop script only prunes dangling images labelled `app=finally`, so unused images from other projects are left alone.

`docker compose up --build` from the repository root does the same thing through `docker-compose.yml`.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | (none) | Needed for AI chat unless `LLM_MOCK=true` |
| `LLM_MOCK` | `false` | `true` gives deterministic replies with no API calls |
| `DHAN_ACESS_TOKEN` | empty | Dhan access token for live NSE prices. Empty means the built-in simulator. `DHAN_ACCESS_TOKEN` is also accepted |
| `DHAN_CLIENT_ID` | from token | Overrides the client ID inside the token |
| `MARKET_SEED` | random | Integer seed that makes the simulator reproducible |

## Develop locally

All Python commands use `uv` and run from `backend/`. The frontend uses npm and runs from `frontend/`.

```bash
# Backend: install dependencies and start the API on port 8000
cd backend
uv run uvicorn app.main:app --port 8000

# Frontend: build the static export and serve it from the backend
cd frontend
npm install
npm run build                    # writes frontend/out
cd ../backend
FINALLY_STATIC_DIR=../frontend/out uv run uvicorn app.main:app --port 8000
```

The database is created on first use at `../db/finally.db` (relative to `backend/`). Set `FINALLY_DB_PATH` to use another file.

## Use the app

- **Watchlist (left).** Shows the ten default tickers with live prices. A price flashes green on an uptick and red on a downtick. The sparkline shows the ticks since you opened the page. Click a ticker to chart it. Type a symbol in the box and press Add to watch it; the × removes it.
- **Chart (top).** The selected ticker's price since the page loaded.
- **Trade bar.** Enter a ticker and quantity, then press Buy or Sell. Orders fill instantly at the current price, with no fees. A rejected order shows the reason (for example, insufficient cash or shares).
- **Heatmap and portfolio value.** The heatmap sizes each position by its value and colours it by unrealised P&L; cash is the grey tile. The chart plots total portfolio value over time.
- **Positions.** Quantity, average cost, live price, value, unrealised P&L and the day change.
- **FinAlly chat (right).** Trades requested in chat execute immediately with no confirmation step, so a request such as "sell everything" sells everything at once. Ask about your portfolio, or ask it to trade or change the watchlist, for example "buy 5 TCS" or "track WIPRO". Executed trades and watchlist changes appear as confirmations under the reply. Hide the panel with its Hide button.

Connection status is in the header: green is connected, yellow is reconnecting and red is disconnected. The browser reconnects by itself.

### Market hours

NSE trades 09:15 to 15:30 IST. Outside those hours live Dhan prices hold their last value, so the watchlist and chart stop moving. The simulator always moves.

## Run the tests

```bash
cd backend
uv run pytest                      # 226 tests: market data, demo, database, portfolio, watchlist, API, chat
uv run ruff check app db tests     # lint

cd ../frontend
npm test                           # 39 tests: components, hooks, API client, layout maths
npm run lint && npm run typecheck

cd ..
docker compose -f test/docker-compose.test.yml down -v
docker compose -f test/docker-compose.test.yml up --build --force-recreate --abort-on-container-exit --exit-code-from playwright
```

The last command runs the Playwright end-to-end suite (`test/tests/finally.spec.ts`, 7 scenarios) against the image in mock-LLM mode with the simulator. Run `down -v` first each time: the app keeps its database inside the container, and the fresh-start scenario expects a new one.

Functional scenarios run against whatever backend is at `BASE_URL`. They trade real (virtual) money and reverse every trade, so run them against the live account only during market hours, or against the simulator:

```bash
cd test
BASE_URL=http://localhost:8000 npm run functional
```

## Live console demo

A terminal watchlist that shows prices updating live: symbol, last traded price, % change vs the previous close, the time of the last tick, and a line chart of the last 40 seconds per symbol (one block character per second, newest on the right, green when the window is rising, red when falling).

```bash
cd backend
uv run python -m demo                  # live Dhan data (token read from the environment)
uv run python -m demo --simulator      # built-in simulator, no token needed
uv run python -m demo --plain 10       # no full-screen UI: print the table for 10 s
```

In the input line at the bottom: `tcs` or `add TCS` adds a symbol, `rm TCS` removes it, `quit` or Ctrl-C exits. Options: `--window 60` (chart width), `--interval 0.5` (seconds per chart point).

Notes:
- Run it in PowerShell, cmd or Windows Terminal. Git Bash cannot host the full-screen view; use `--plain` there.
- An expired Dhan token stops the demo with a message (it does not silently fall back to the simulator); generate a new token or add `--simulator`.

## Use live Dhan data

1. Generate an access token: web.dhan.co, My Profile, *Access DhanHQ APIs* (valid 24 h; needs the Data API plan).
2. Put it in the project `.env` as `DHAN_ACESS_TOKEN=...` (quotes are fine), or set it in your shell.
3. Start the app as above. The header and watchlist carry live NSE prices.
4. When the token expires the source turns unhealthy (`/api/health` reports `market_source_healthy: false`). Generate a new token and restart.

**Check which source is active:** `curl localhost:8000/api/health` reports `"market_source": "dhan"` or `"simulator"`.

## API reference

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Status, market source and its health |
| GET | `/api/stream/prices` | SSE: one event per change with every priced ticker |
| GET | `/api/portfolio` | Cash, positions, total value, unrealised P&L |
| POST | `/api/portfolio/trade` | `{ticker, quantity, side}`; 400 with `detail` when rejected |
| GET | `/api/portfolio/history` | Snapshots, oldest first. `?range=1h\|1d\|7d\|all` and `?limit=N` |
| GET | `/api/watchlist` | Watched tickers with prices |
| POST | `/api/watchlist` | `{ticker}`; 201 added, 409 duplicate, 400 unknown or malformed |
| DELETE | `/api/watchlist/{ticker}` | 204 removed, 404 not watched |
| POST | `/api/chat` | `{message}`; returns `message`, `trades` and `watchlist_changes` |

## Try the market data (simulator)

No token needed. A minimal app that only streams prices:

```python
# backend/stream_app.py (not demo.py, which would clash with the demo package)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import DEFAULT_WATCHLIST, PriceCache, create_market_source, create_stream_router

cache = PriceCache()
source = create_market_source(cache)

@asynccontextmanager
async def lifespan(app):
    await source.start(DEFAULT_WATCHLIST)
    yield
    await source.stop()

app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(cache))
```

```bash
uv run --with uvicorn uvicorn stream_app:app --port 8000
curl -N localhost:8000/api/stream/prices
```

## Lessons learnt

- **Quoted env values.** `docker --env-file` keeps quotes, so `"eyJ..."` was sent to Dhan with the quote characters and failed with `DH-901`, while the same token worked in a script that stripped them. The backend strips quotes.
- **Dhan trade time is IST encoded as UTC.** `15:54:52` IST arrives as the epoch of `15:54:52 UTC`. Ticks are stamped with receive time instead.
- **REST cannot give the previous close.** After the close `ohlc.close` equals the last price and `net_change` is 0. Use the WebSocket Previous Close packet.
- **Test endless streams without `httpx.ASGITransport`.** It buffers the whole response, so an SSE test hangs forever. Test the route function, and verify real streaming against uvicorn.
- **Check determinism across ranges.** A history bar whose open depended on the requested range slipped through until a wide-vs-narrow test.
- **Bash heredocs choke on very long commands on Windows.** Write files with the editor tool.
- **Empty env values override inherited ones.** A shell or machine-wide `DHAN_ACESS_TOKEN` made a local run use live Dhan prices, which are frozen outside market hours. Setting the variable to an empty string forces the simulator.
- **Playwright cannot reach `http://app:8000` by service name.** Chromium failed with `ERR_SSL_PROTOCOL_ERROR` even though Node reached it. The E2E service shares the app's network namespace and uses `localhost:8000` instead.
- **A route set after the page connects does not affect the open stream.** The reconnect test has to route the stream before navigating.
- **The E2E app keeps its database in the container.** Without `down -v` between runs, the fresh-start scenario sees trades from the previous run.
- **Fractional treemap tiles can go negative.** A position worth 0.1% of the portfolio is about 1 px wide, so inset rectangles must be clamped at zero.
- **Prices stop changing outside NSE hours.** A stream that sends only on change looks broken at night; check the health endpoint and the market clock first.

## Known behaviour (recorded deviations)

These are intentional and match the code. The full list is in [PLAN.md section 13](../planning/PLAN.md).

- **Stream sends on change.** `/api/stream/prices` sends an event when prices change, not on a fixed timer. Outside market hours with live Dhan data, the stream can be quiet for long stretches.
- **Health returns 200 with a status field.** `/api/health` is HTTP 200 always. Read `"status"`: `"ok"` means the market source is healthy, `"degraded"` means it is not.
- **First buy on an unwatched ticker waits for its first price.** The trade waits up to 5 seconds for the first tick, then fills at that price. If no tick arrives, it is rejected and the subscription is released.
- **Simulator accepts any valid symbol.** In simulator mode, an unknown but well-formed symbol (for example `NOPE`) can be added to the watchlist and traded, and gets a deterministic price. Dhan mode rejects non-NSE symbols.
- **Chat is not reloaded on refresh.** Messages are kept in the browser for the session. The backend stores them, but no endpoint returns them yet.
- **Docker Desktop must be running before the start script.** Without the engine, `docker build` and `docker run` fail with a named-pipe error. The start script does not start Docker itself.
- **The start script passes `.env` to Docker, not to the shell.** The scripts never read the file. A shell that lacks `DHAN_ACESS_TOKEN` does not mean the container lacks it. Check `/api/health` for `market_source`.
- **Prices arrive within seconds of start.** Dhan sends the last price and previous close on subscribe, so the watchlist fills within a few seconds of start, in or out of market hours.
- **Git Bash `TZ=` does not change the clock.** `TZ=Asia/Kolkata date` printed UTC, so early timing notes were wrong by 5 h 30 min. Read IST from PowerShell (`Get-Date`) or add 5 h 30 min to UTC.
- **Persistent volume keeps earlier trades.** `finally-data` keeps the portfolio between container restarts and image rebuilds, so a live test starts from whatever state the app already holds.

## Live end-to-end suite

`test/live/live.spec.ts` drives the real UI against the live feed and the real account, with relative assertions and reversed trades. Run it during market hours with the app running on port 8000:

```bash
cd test
npm run test:live
```

It leaves the holdings and watchlist as it found them. It does not cover mobile width, token expiry or the simulator.
