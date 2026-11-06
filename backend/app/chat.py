"""Chat turn: portfolio context, model call, auto-execution and persistence."""

from __future__ import annotations

from dataclasses import asdict

from app.llm.client import ChatModel
from app.llm.prompt import build_messages
from app.llm.schema import ChatReply
from app.market import MarketDataError
from app.portfolio import PortfolioService, TradeRejectedError
from app.repository import insert_chat_message, read_chat_history
from app.watchlist import WatchlistError, WatchlistService
from db import Database


class ChatService:
    """Answers one user message, applying the trades and watchlist changes the model asks for.

    Each action goes through the same checks as a manual trade or watchlist edit. A failed
    action adds its error to the reply text; the model is not called again.
    """

    def __init__(
        self,
        db: Database,
        portfolio: PortfolioService,
        watchlist: WatchlistService,
        model: ChatModel,
    ) -> None:
        self.db = db
        self.portfolio = portfolio
        self.watchlist = watchlist
        self.model = model

    async def reply(self, user_message: str) -> dict:
        with self.db.connect() as conn:
            history = [dict(row) for row in read_chat_history(conn)]
        messages = build_messages(history, self._context(), user_message)
        model_reply: ChatReply = await self.model.reply(messages)

        trades, trade_errors = await self._apply_trades(model_reply)
        changes, change_errors = await self._apply_watchlist(model_reply)
        text = "\n".join([model_reply.message, *trade_errors, *change_errors])

        actions = {"trades": trades or None, "watchlist_changes": changes or None}
        with self.db.connect() as conn:
            insert_chat_message(conn, "user", user_message)
            insert_chat_message(conn, "assistant", text, actions)
        return {"message": text, **actions}

    def _context(self) -> dict:
        portfolio = self.portfolio.get_portfolio()
        watched = self.watchlist.list_tickers()
        return {
            "cash_balance": portfolio.cash_balance,
            "total_value": portfolio.total_value,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "positions": [asdict(position) for position in portfolio.positions],
            "watchlist": [
                {
                    "ticker": entry.ticker,
                    "price": entry.price,
                    "day_change_percent": entry.day_change_percent,
                }
                for entry in watched
            ],
        }

    async def _apply_trades(self, model_reply: ChatReply) -> tuple[list[dict], list[str]]:
        executed: list[dict] = []
        errors: list[str] = []
        for trade in model_reply.trades:
            try:
                result = await self.portfolio.execute_trade(
                    trade.ticker, trade.quantity, trade.side
                )
            except (TradeRejectedError, MarketDataError) as exc:
                errors.append(
                    f"Trade not executed ({trade.side} {trade.quantity:g} {trade.ticker}): {exc}"
                )
                continue
            executed.append(
                {
                    "ticker": result.ticker,
                    "side": result.side,
                    "quantity": result.quantity,
                    "price": result.price,
                }
            )
        return executed, errors

    async def _apply_watchlist(self, model_reply: ChatReply) -> tuple[list[dict], list[str]]:
        applied: list[dict] = []
        errors: list[str] = []
        for change in model_reply.watchlist_changes:
            try:
                if change.action == "add":
                    await self.watchlist.add(change.ticker)
                else:
                    await self.watchlist.remove(change.ticker)
            except (WatchlistError, MarketDataError) as exc:
                errors.append(
                    f"Watchlist change not applied ({change.action} {change.ticker}): {exc}"
                )
                continue
            applied.append({"ticker": change.ticker.strip().upper(), "action": change.action})
        return applied, errors
