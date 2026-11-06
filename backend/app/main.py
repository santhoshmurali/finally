"""FastAPI application: wires the database, market source, services and routes.

Run with `uv run uvicorn app.main:app` from `backend/`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat import create_chat_router
from app.api.errors import register_error_handlers
from app.api.portfolio import create_portfolio_router
from app.api.system import create_system_router
from app.api.watchlist import create_watchlist_router
from app.chat import ChatService
from app.config import Settings
from app.llm.client import ChatModel, LiteLLMChatModel, MockChatModel
from app.market import (
    DEFAULT_WATCHLIST,
    MarketDataSource,
    PriceCache,
    create_market_source,
    create_stream_router,
)
from app.portfolio import PortfolioService
from app.priced_set import priced_tickers
from app.snapshots import run_snapshots
from app.watchlist import WatchlistService
from db import Database


def create_app(
    settings: Settings | None = None,
    make_source: Callable[[PriceCache], MarketDataSource] = create_market_source,
    make_model: Callable[[Settings], ChatModel] | None = None,
) -> FastAPI:
    """Build the app. Tests inject `make_source` and `make_model` to avoid live services."""
    settings = settings or Settings.from_env()
    cache = PriceCache()
    db = Database(settings.db_path, DEFAULT_WATCHLIST)
    source = make_source(cache)
    portfolio = PortfolioService(db, cache, source)
    watchlist = WatchlistService(db, cache, source)
    model = make_model(settings) if make_model else default_model(settings)
    chat = ChatService(db, portfolio, watchlist, model)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        db.initialize()
        await source.start(priced_tickers(db))
        portfolio.record_snapshot()
        snapshots = asyncio.create_task(run_snapshots(portfolio))
        try:
            yield
        finally:
            snapshots.cancel()
            await source.stop()

    app = FastAPI(title="FinAlly", version="0.1.0", lifespan=lifespan)
    app.include_router(create_system_router(source))
    app.include_router(create_stream_router(cache))
    app.include_router(create_portfolio_router(portfolio))
    app.include_router(create_watchlist_router(watchlist))
    app.include_router(create_chat_router(chat))
    register_error_handlers(app)
    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app


def default_model(settings: Settings) -> ChatModel:
    """Deterministic mock when LLM_MOCK=true, otherwise the OpenRouter/Cerebras model."""
    if settings.llm_mock:
        return MockChatModel()
    return LiteLLMChatModel(settings.openrouter_api_key)


app = create_app()
