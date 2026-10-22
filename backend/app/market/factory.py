"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .seed_prices import NSE_DEFAULTS, US_DEFAULTS
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def _dhan_credentials() -> tuple[str, str] | None:
    """Return (client_id, access_token) if Dhan is configured, else None.

    Raises RuntimeError on a half-configured setup (token without client id).
    """
    token = os.environ.get("DHANHQ_API_KEY", "").strip()
    if not token:
        return None
    client_id = os.environ.get("DHANHQ_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "DHANHQ_API_KEY is set but DHANHQ_CLIENT_ID is missing; Dhan requires both. "
            "Unset DHANHQ_API_KEY to use the simulator."
        )
    return client_id, token


def default_watchlist() -> list[str]:
    """Seed watchlist for a fresh database; depends on the active source's market."""
    return list(NSE_DEFAULTS if _dhan_credentials() else US_DEFAULTS)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - DHANHQ_API_KEY set (needs DHANHQ_CLIENT_ID) → DhanDataSource (real NSE data, INR)
    - else MASSIVE_API_KEY set → MassiveDataSource (legacy)
    - else → SimulatorDataSource (GBM simulation; MARKET_SEED makes it deterministic)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    creds = _dhan_credentials()
    if creds:
        from .dhan.source import DhanDataSource  # lazy: keeps httpx cost out of sim mode

        client_id, token = creds
        base_url = os.environ.get("DHANHQ_BASE_URL", "").strip() or None
        if base_url and "sandbox" in base_url:
            logger.warning(
                "DHANHQ_BASE_URL is the Dhan sandbox, which has no /marketfeed/* quote "
                "endpoints: live prices will not work"
            )
        logger.info("Market data source: DhanHQ (real data, INR)")
        return DhanDataSource(
            client_id,
            token,
            price_cache,
            cache_dir=Path(os.environ.get("DHANHQ_CACHE_DIR", "/app/db")),
            poll_interval=float(os.environ.get("DHANHQ_POLL_INTERVAL", "2.0")),
            base_url=base_url,
        )

    massive_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if massive_key:
        logger.info("Market data source: Massive API (legacy real data)")
        return MassiveDataSource(api_key=massive_key, price_cache=price_cache)

    logger.info("Market data source: GBM Simulator")
    seed = os.environ.get("MARKET_SEED", "").strip()
    return SimulatorDataSource(price_cache=price_cache, seed=int(seed) if seed else None)
