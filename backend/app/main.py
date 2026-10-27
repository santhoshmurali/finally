"""FastAPI application: lifespan, routers, error mapping and the static frontend."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import chat, health, portfolio, watchlist
from app.market import PriceCache, create_market_source, create_stream_router
from app.services.errors import ServiceError
from app.services.snapshots import record_snapshot, snapshot_loop
from app.state import AppState
from db.connection import init_db, transaction
from db.positions import list_positions
from db.watchlist import list_watchlist

STATIC_DIR = Path(os.environ.get("FINALLY_STATIC_DIR", "../frontend/out"))
cache = PriceCache()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the database, the price source and the snapshot task; stop them on shutdown."""
    init_db()
    source = create_market_source(cache)
    state = AppState(cache=cache, source=source)
    await source.start(_priced_tickers())
    record_snapshot(state)
    snapshot_task = asyncio.create_task(snapshot_loop(state))
    app.state.app_state = state
    yield
    snapshot_task.cancel()
    await source.stop()


def _priced_tickers() -> list[str]:
    """Watchlist plus held tickers, each once, in that order."""
    with transaction() as conn:
        watched = [entry.ticker for entry in list_watchlist(conn)]
        held = [position.ticker for position in list_positions(conn)]
    return list(dict.fromkeys(watched + held))


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(chat.router)
app.include_router(create_stream_router(cache))


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
