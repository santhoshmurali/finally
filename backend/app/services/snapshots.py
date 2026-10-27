"""Portfolio value snapshots: the history behind the P&L chart."""

import asyncio

from app.services.portfolio import build_portfolio
from app.state import AppState
from db.connection import transaction
from db.models import Snapshot
from db.snapshots import insert_snapshot, list_snapshots

SNAPSHOT_INTERVAL_SECONDS = 30


def record_snapshot(state: AppState) -> None:
    """Store the current total portfolio value."""
    total_value = build_portfolio(state).total_value
    with transaction() as conn:
        insert_snapshot(conn, total_value)


async def snapshot_loop(state: AppState) -> None:
    """Record a snapshot every `SNAPSHOT_INTERVAL_SECONDS` until cancelled."""
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
        record_snapshot(state)


def snapshot_history(limit: int | None) -> list[Snapshot]:
    """Oldest first. `limit` keeps only the newest N."""
    with transaction() as conn:
        return list_snapshots(conn, limit)
