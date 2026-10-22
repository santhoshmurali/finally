"""Market data: unified interface, Dhan live source and the built-in simulator."""

from .cache import PriceCache
from .errors import (
    AuthenticationError,
    DataUnavailableError,
    MarketDataError,
    RateLimitError,
    UnsupportedTickerError,
)
from .factory import create_market_source
from .interface import MarketDataSource
from .models import Bar, PriceUpdate
from .seed_prices import DEFAULT_WATCHLIST
from .stream import create_stream_router

__all__ = [
    "DEFAULT_WATCHLIST",
    "AuthenticationError",
    "Bar",
    "DataUnavailableError",
    "MarketDataError",
    "MarketDataSource",
    "PriceCache",
    "PriceUpdate",
    "RateLimitError",
    "UnsupportedTickerError",
    "create_market_source",
    "create_stream_router",
]
