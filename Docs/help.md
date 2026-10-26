# FinAlly - Help

All Python commands use `uv`. Run them from `backend/`.

## Run the tests

```bash
cd backend
uv run pytest                      # 163 tests (125 market data + 38 demo)
uv run pytest --cov=app            # coverage (100%)
uv run ruff check app tests        # lint
```

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

## Try the market data (simulator)

No token needed. Create a tiny app in `backend/stream_app.py` (not `demo.py`, which would clash with the `demo` package) that wires the pieces:

```python
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

## Use live Dhan data

1. Generate an access token: web.dhan.co, My Profile, *Access DhanHQ APIs* (valid 24 h; needs the Data API plan).
2. Put it in the project `.env` as `DHAN_ACESS_TOKEN=...` (quotes are fine).
3. Start the same app with the variables loaded: `uv run --with uvicorn --env-file ../.env uvicorn stream_app:app --port 8000`. The stream now carries live NSE prices (outside market hours: the last price and previous close, then quiet). Health checks use `source.healthy()`.
4. When the token expires the source turns unhealthy: generate a new token and restart.

## Lessons learnt

- **Quoted env values.** `docker --env-file` keeps quotes, so `"eyJ..."` was sent to Dhan with the quote characters and failed with `DH-901`, while the same token worked in a script that stripped them. The backend strips quotes.
- **Dhan trade time is IST encoded as UTC.** `15:54:52` IST arrives as the epoch of `15:54:52 UTC`. Ticks are stamped with receive time instead.
- **REST cannot give the previous close.** After the close `ohlc.close` equals the last price and `net_change` is 0. Use the WebSocket Previous Close packet.
- **Test endless streams without `httpx.ASGITransport`.** It buffers the whole response, so an SSE test hangs forever. Test the route function, and verify real streaming against uvicorn.
- **Check determinism across ranges.** A history bar whose open depended on the requested range slipped through until a wide-vs-narrow test.
- **Bash heredocs choke on very long commands on Windows.** Write files with the editor tool.
