# FinAlly - Help

All Python commands use `uv`. Run them from `backend/`.

## Run the tests

```bash
cd backend
uv run pytest                      # 252 tests (market, db, services, API, LLM, demo)
uv run ruff check app db tests     # lint

cd ../frontend
npm test                           # 49 Vitest tests
npm run build                      # static export to frontend/out

cd ../test
npx playwright test                # 10 E2E tests (starts the backend with the simulator and mock LLM)
```

## Run the app

```bash
cd backend
uv run uvicorn app.main:app --port 8000   # serves the API, and the UI when frontend/out exists
```

Open http://localhost:8000. The UI uses the simulator when `DHAN_ACESS_TOKEN` is empty, and the mock LLM when `LLM_MOCK=true`.

With Docker (Windows, verified): `scripts/start_windows.ps1` builds the image if needed, starts the container, and waits until it is running. If the container exits at startup, the script prints the last log lines and exits 1. `scripts/stop_windows.ps1` removes the container and the `finally` image, and keeps the `finally-data` volume. Base images (`python`, `node`, `uv`, `playwright`) are kept for reuse. The macOS scripts are not part of testing.

Before starting, check `.env`: each key name must be exact, with no space before `=`. A Dhan token lasts 24 hours. When it expires, the app exits at startup with `Dhan access token has expired`, so either generate a new token or clear `DHAN_ACESS_TOKEN` to use the simulator.

## Live console demo

A terminal watchlist that shows prices updating live: symbol, last traded price, % change vs the previous close, the time of the last tick, and a line chart of the last 40 seconds per symbol (one block character per second, newest on the right, green when the window is rising, red when falling).

```bash
cd backend
uv run python -m demo                  # live Dhan data (token read from ../.env)
uv run python -m demo --simulator      # built-in simulator, no token needed
uv run python -m demo --plain 10       # no full-screen UI: print the table for 10 s
```

Default watchlist: the ten largest NIFTY 50 stocks already used by the backend (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, BHARTIARTL, ITC, LT, HINDUNILVR).

In the input line at the bottom: `tcs` or `add TCS` adds a symbol (Dhan accepts NSE equities only and tells you otherwise), `rm TCS` removes it, `quit` or Ctrl-C exits. Options: `--window 60` (chart width), `--interval 0.5` (seconds per chart point).

Notes:
- Run it in PowerShell, cmd or Windows Terminal. Git Bash cannot host the full-screen view; use `--plain` there.
- Outside NSE hours (09:15 to 15:30 IST) Dhan prices do not move, so only the UPDATED column and the simulator show motion. The UPDATED column is the time of the last tick, so quiet stocks visibly go stale between trades.
- An expired Dhan token stops the demo with a message (it does not silently fall back to the simulator); generate a new token or add `--simulator`.

## Try the app with the simulator

No token needed. The app uses the simulator whenever `DHAN_ACESS_TOKEN` is empty.

```bash
cd backend
uv run uvicorn app.main:app --port 8000
curl -N localhost:8000/api/stream/prices     # live price events
curl localhost:8000/api/health               # {"status":"ok","market_source":"simulator",...}
```

## Use live Dhan data

1. Generate an access token: web.dhan.co, My Profile, *Access DhanHQ APIs* (valid 24 h; needs the Data API plan).
2. Put it in the project `.env` as `DHAN_ACESS_TOKEN=...` (quotes are fine).
3. Start the app with the variables loaded: `uv run --env-file ../.env uvicorn app.main:app --port 8000`, or use the Docker scripts. The stream carries live NSE prices (outside market hours: the last price and previous close, then quiet). `/api/health` reports `market_source: dhan`.
4. When the token expires the app refuses to start, so generate a new token and restart.

## Lessons learnt

- **Quoted env values.** `docker --env-file` keeps quotes, so `"eyJ..."` was sent to Dhan with the quote characters and failed with `DH-901`, while the same token worked in a script that stripped them. The backend strips quotes.
- **Dhan trade time is IST encoded as UTC.** `15:54:52` IST arrives as the epoch of `15:54:52 UTC`. Ticks are stamped with receive time instead.
- **REST cannot give the previous close.** After the close `ohlc.close` equals the last price and `net_change` is 0. Use the WebSocket Previous Close packet.
- **Test endless streams without `httpx.ASGITransport`.** It buffers the whole response, so an SSE test hangs forever. Test the route function, and verify real streaming against uvicorn.
- **Check determinism across ranges.** A history bar whose open depended on the requested range slipped through until a wide-vs-narrow test.
- **Bash heredocs choke on very long commands on Windows.** Write files with the editor tool.
- **A hidden error hid the real bug.** `start_windows.ps1` sent its `docker run` error to `$null`, and the message blamed port 8000. The real cause was a missing image name. Do not hide stderr in scripts.
- **Spaces in `.env` keys.** `DHAN_ACESS_TOKEN ` (with a space before `=`) was rejected by Docker. Check key names exactly.
- **Expired token fails loudly.** A 24-hour Dhan token that expired makes the app exit at startup. The start script now checks the container and exits 1 with the log lines, so this does not look like a success.
- **Chromium upgrades single-label hosts to HTTPS.** The E2E container could not reach `http://app:8000`, because Chromium's HSTS preload treats the `.app` TLD as HTTPS-only. The compose file uses the alias `finally.internal`.
- **Named volumes shadow directories.** Mounting `finally-data` at `/app/db` hides anything in `/app/db` in the image. The backend code sits at `/app/backend`, and the database volume at `/app/db`.
- **Flaky PyPI downloads break image builds.** Four of ten downloads of the same wheel were cut short. The Dockerfile sets `UV_HTTP_RETRIES=10` and `UV_HTTP_TIMEOUT=120`.
- **Route interception after the stream opens never fires.** A Playwright `page.route` set up after the page opened its SSE stream never sees the stream fail. Install the route before `page.goto`.
- **Parallel frontend work drifts from the test hooks.** Hook names built from memory did not match the E2E specs. Keep the hook table in `planning/TEAM_CONTRACT.md` as the single source, and check the built bundle for the names.
