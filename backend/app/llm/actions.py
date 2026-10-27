"""Runs the trades and watchlist changes the LLM asked for, collecting the rejected ones."""

from app.llm.schemas import ExecutedTrade, LLMTrade, LLMWatchlistChange
from app.services.errors import ServiceError
from app.services.trading import execute_trade
from app.services.watchlist import add_to_watchlist, remove_from_watchlist
from app.state import AppState


async def run_trades(
    state: AppState, trades: list[LLMTrade]
) -> tuple[list[ExecutedTrade], list[str]]:
    """Execute each trade in order. Returns the executed trades and rejection messages."""
    executed: list[ExecutedTrade] = []
    failures: list[str] = []
    for trade in trades:
        try:
            done = await execute_trade(state, trade.ticker, trade.quantity, trade.side)
        except ServiceError as error:
            failures.append(error.message)
        else:
            executed.append(
                ExecutedTrade(
                    ticker=done.ticker, quantity=done.quantity, side=done.side, price=done.price
                )
            )
    return executed, failures


async def run_watchlist_changes(
    state: AppState, changes: list[LLMWatchlistChange]
) -> tuple[list[LLMWatchlistChange], list[str]]:
    """Apply each watchlist change in order. Returns the applied changes and rejected messages."""
    applied: list[LLMWatchlistChange] = []
    failures: list[str] = []
    for change in changes:
        try:
            await _apply_watchlist_change(state, change)
        except ServiceError as error:
            failures.append(error.message)
        else:
            applied.append(change)
    return applied, failures


async def _apply_watchlist_change(state: AppState, change: LLMWatchlistChange) -> None:
    if change.action == "add":
        await add_to_watchlist(state, change.ticker)
    else:
        await remove_from_watchlist(state, change.ticker)
