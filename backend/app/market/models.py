"""Core market data types shared by every price source."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Latest price of one ticker.

    `previous_price` is the prior tick (drives the UI flash). `previous_close`
    is the prior session close (drives the day change); it equals `price`
    until a real value is known.
    """

    ticker: str
    price: float
    previous_price: float
    previous_close: float
    timestamp: float

    @property
    def change(self) -> float:
        """Absolute change versus the previous tick."""
        return round(self.price - self.previous_price, 4)

    @property
    def direction(self) -> str:
        """`up`, `down` or `flat` versus the previous tick."""
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float:
        """Absolute change versus the previous session close."""
        return round(self.price - self.previous_close, 4)

    @property
    def day_change_percent(self) -> float:
        """Percent change versus the previous session close."""
        if self.previous_close == 0:
            return 0.0
        return round((self.price - self.previous_close) / self.previous_close * 100, 4)

    def to_dict(self) -> dict:
        """JSON-ready form used by the SSE stream."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "previous_close": self.previous_close,
            "timestamp": self.timestamp,
            "change": self.change,
            "direction": self.direction,
            "day_change": self.day_change,
            "day_change_percent": self.day_change_percent,
        }


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV candle."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int


def now() -> float:
    """Current Unix time in seconds."""
    return time.time()
