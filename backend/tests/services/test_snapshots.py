"""Snapshot history: oldest first, optionally limited to the newest entries."""

from app.services.portfolio import build_portfolio
from app.services.snapshots import record_snapshot, snapshot_history
from app.services.trading import execute_trade


async def test_history_is_oldest_first_and_limit_keeps_the_newest(state):
    await execute_trade(state, "TCS", 10, "buy")
    state.cache.update("TCS", 2700.0)
    record_snapshot(state)

    everything = snapshot_history(None)
    newest = snapshot_history(1)

    assert [snapshot.total_value for snapshot in everything] == [1_000_000.0, 1_002_000.0]
    assert [snapshot.total_value for snapshot in newest] == [1_002_000.0]
    assert build_portfolio(state).total_value == 1_002_000.0
