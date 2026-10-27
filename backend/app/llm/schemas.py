"""Pydantic models for the LLM structured reply and the chat API."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

Ticker = Annotated[str, AfterValidator(str.upper)]


class LLMTrade(BaseModel):
    """A trade the LLM wants executed."""

    ticker: Ticker
    quantity: float = Field(gt=0)
    side: Literal["buy", "sell"]


class LLMWatchlistChange(BaseModel):
    """A watchlist add or remove the LLM wants applied."""

    ticker: Ticker
    action: Literal["add", "remove"]


class LLMReply(BaseModel):
    """Structured reply the LLM must return for every chat message."""

    message: str
    trades: list[LLMTrade] = []
    watchlist_changes: list[LLMWatchlistChange] = []


class ChatRequest(BaseModel):
    """Body of POST /api/chat."""

    message: str = Field(min_length=1)


class ExecutedTrade(BaseModel):
    """A trade that was executed for a chat reply."""

    ticker: Ticker
    quantity: float
    side: Literal["buy", "sell"]
    price: float


class ChatResponse(BaseModel):
    """Body returned by POST /api/chat."""

    message: str
    trades: list[ExecutedTrade] | None
    watchlist_changes: list[LLMWatchlistChange] | None


class ChatHistoryItem(BaseModel):
    """One stored chat message in GET /api/chat/history."""

    role: Literal["user", "assistant"]
    content: str
    actions: dict | None
    created_at: str
