"""Row types returned by the repository functions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """One held ticker with its weighted average cost."""

    ticker: str
    quantity: float
    avg_cost: float
    updated_at: str


@dataclass(frozen=True, slots=True)
class Trade:
    """One executed buy or sell."""

    id: str
    ticker: str
    side: str
    quantity: float
    price: float
    executed_at: str


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    """One ticker on the watchlist."""

    ticker: str
    added_at: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Total portfolio value at one moment."""

    total_value: float
    recorded_at: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message in the assistant conversation."""

    role: str
    content: str
    actions: list[dict] | None
    created_at: str
