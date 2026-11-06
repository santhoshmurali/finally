"""Background task that records the portfolio value on a fixed interval."""

from __future__ import annotations

import asyncio

from app.portfolio import PortfolioService

SNAPSHOT_INTERVAL_SECONDS = 30.0


async def run_snapshots(
    portfolio: PortfolioService, interval: float = SNAPSHOT_INTERVAL_SECONDS
) -> None:
    """Record the total value every `interval` seconds until cancelled."""
    while True:
        await asyncio.sleep(interval)
        portfolio.record_snapshot()
