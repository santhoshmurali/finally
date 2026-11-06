"""Structured reply the LLM must return. Used both as the response format and for validation."""

from typing import Literal

from pydantic import BaseModel, Field


class TradeAction(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    side: Literal["buy", "sell"]


class WatchlistAction(BaseModel):
    ticker: str
    action: Literal["add", "remove"]


class ChatReply(BaseModel):
    """What FinAlly says, plus the trades and watchlist changes to apply."""

    message: str
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistAction] = Field(default_factory=list)
