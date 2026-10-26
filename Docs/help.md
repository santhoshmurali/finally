# FinAlly - Help

All Python commands use `uv`. Run them from `backend/`.

## Run the tests

```bash
cd backend
uv run pytest                      # 125 tests
uv run pytest --cov=app            # coverage (100%)
uv run ruff check app tests        # lint
```

## Try the market data (simulator)

No token needed. Create a tiny app (for example `demo.py`) that wires the pieces:

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
uv run --with uvicorn uvicorn demo:app --port 8000
curl -N localhost:8000/api/stream/prices
```

## Use live Dhan data

1. Generate an access token: web.dhan.co, My Profile, *Access DhanHQ APIs* (valid 24 h; needs the Data API plan).
2. Put it in the project `.env` as `DHAN_ACESS_TOKEN=...` (quotes are fine).
3. Start the same app with the variables loaded: `uv run --with uvicorn --env-file ../.env uvicorn demo:app --port 8000`. The stream now carries live NSE prices (outside market hours: the last price and previous close, then quiet). Health checks use `source.healthy()`.
4. When the token expires the source turns unhealthy: generate a new token and restart.

## Lessons learnt

- **Quoted env values.** `docker --env-file` keeps quotes, so `"eyJ..."` was sent to Dhan with the quote characters and failed with `DH-901`, while the same token worked in a script that stripped them. The backend strips quotes.
- **Dhan trade time is IST encoded as UTC.** `15:54:52` IST arrives as the epoch of `15:54:52 UTC`. Ticks are stamped with receive time instead.
- **REST cannot give the previous close.** After the close `ohlc.close` equals the last price and `net_change` is 0. Use the WebSocket Previous Close packet.
- **Test endless streams without `httpx.ASGITransport`.** It buffers the whole response, so an SSE test hangs forever. Test the route function, and verify real streaming against uvicorn.
- **Check determinism across ranges.** A history bar whose open depended on the requested range slipped through until a wide-vs-narrow test.
- **Bash heredocs choke on very long commands on Windows.** Write files with the editor tool.
