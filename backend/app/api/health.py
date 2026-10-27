"""Health check used by Docker and deployment."""

from fastapi import APIRouter

from app.api.deps import StateDep
from app.market.dhan.source import DhanDataSource

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(state: StateDep) -> dict[str, object]:
    """Always 200 while the server is up. `market_healthy` reports the price source."""
    return {
        "status": "ok",
        "market_source": "dhan" if isinstance(state.source, DhanDataSource) else "simulator",
        "market_healthy": state.source.healthy(),
    }
