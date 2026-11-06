"""Request bodies accepted by the REST API."""

from pydantic import BaseModel, Field


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str


class WatchlistRequest(BaseModel):
    ticker: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
