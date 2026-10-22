"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    Bar                 - Daily OHLCV candle
    PriceCache          - Thread-safe in-memory price store
    MarketDataSource    - Abstract interface for data providers
    MarketDataError, CapabilityError, UnknownTickerError - error hierarchy
    create_market_data_source - Factory that selects Dhan, Massive or the simulator
    default_watchlist   - Seed watchlist matching the active source
    create_stream_router - FastAPI router factory for SSE endpoint
"""

from .cache import PriceCache
from .factory import create_market_data_source, default_watchlist
from .interface import (
    CapabilityError,
    MarketDataError,
    MarketDataSource,
    UnknownTickerError,
)
from .models import Bar, PriceUpdate
from .stream import create_stream_router

__all__ = [
    "Bar",
    "CapabilityError",
    "MarketDataError",
    "MarketDataSource",
    "PriceCache",
    "PriceUpdate",
    "UnknownTickerError",
    "create_market_data_source",
    "create_stream_router",
    "default_watchlist",
]
