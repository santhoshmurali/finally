"""System routes: the health check used by Docker and deployment."""

from __future__ import annotations

from fastapi import APIRouter

from app.market import MarketDataSource
from app.market.dhan.source import DhanDataSource


def create_system_router(source: MarketDataSource) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["system"])
    source_name = "dhan" if isinstance(source, DhanDataSource) else "simulator"

    @router.get("/health")
    def health() -> dict:
        healthy = source.healthy()
        return {
            "status": "ok" if healthy else "degraded",
            "market_source": source_name,
            "market_source_healthy": healthy,
        }

    return router
