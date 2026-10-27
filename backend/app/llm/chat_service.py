"""One chat turn: ask the LLM, run its trades and watchlist changes, and store the exchange."""

from app.llm.actions import run_trades, run_watchlist_changes
from app.llm.client import request_reply
from app.llm.prompt import build_messages
from app.llm.schemas import ChatResponse, ExecutedTrade, LLMWatchlistChange
from app.services.portfolio import build_portfolio
from app.services.watchlist import list_watchlist
from app.state import AppState
from db.chat import insert_chat_message, list_chat_messages
from db.connection import transaction


async def handle_chat(state: AppState, message: str) -> ChatResponse:
    """Run one chat turn.

    Raises LLMError, with nothing stored, when the LLM call fails or its reply is malformed.
    """
    with transaction() as conn:
        history = list_chat_messages(conn)
    messages = build_messages(build_portfolio(state), list_watchlist(state), history, message)
    reply = await request_reply(messages)
    with transaction() as conn:
        insert_chat_message(conn, "user", message, None)
    executed, trade_failures = await run_trades(state, reply.trades)
    applied, watchlist_failures = await run_watchlist_changes(state, reply.watchlist_changes)
    text = " ".join([reply.message, *trade_failures, *watchlist_failures])
    with transaction() as conn:
        insert_chat_message(conn, "assistant", text, _actions(executed, applied))
    return ChatResponse(
        message=text,
        trades=executed or None,
        watchlist_changes=applied or None,
    )


def _actions(executed: list[ExecutedTrade], applied: list[LLMWatchlistChange]) -> dict | None:
    """Stored form of what a reply did, as the POST reply carries it. None when nothing ran."""
    if not executed and not applied:
        return None
    return {
        "trades": [trade.model_dump() for trade in executed] or None,
        "watchlist_changes": [change.model_dump() for change in applied] or None,
    }
