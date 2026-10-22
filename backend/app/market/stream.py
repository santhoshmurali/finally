"""SSE endpoint that pushes cached prices to the browser (`GET /api/stream/prices`)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

STREAM_INTERVAL = 0.5
RETRY_MILLISECONDS = 1000


def create_stream_router(cache: PriceCache, interval: float = STREAM_INTERVAL) -> APIRouter:
    """Router exposing the price stream for every ticker currently in `cache`."""
    router = APIRouter(prefix="/api/stream", tags=["market"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            price_events(cache, request, interval),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def price_events(cache: PriceCache, request: Request, interval: float) -> AsyncIterator[str]:
    """Yield one SSE event per interval with all prices, only when something changed."""
    yield f"retry: {RETRY_MILLISECONDS}\n\n"
    last_version = -1
    while not await request.is_disconnected():
        if cache.version != last_version:
            last_version = cache.version
            prices = {ticker: u.to_dict() for ticker, u in cache.get_all().items()}
            yield f"data: {json.dumps(prices)}\n\n"
        await asyncio.sleep(interval)
