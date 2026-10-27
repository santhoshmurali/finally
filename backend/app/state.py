"""Process-wide objects shared by the services and the routes."""

from dataclasses import dataclass

from app.market import MarketDataSource, PriceCache


@dataclass
class AppState:
    """Price cache and live market source, created once when the app starts."""

    cache: PriceCache
    source: MarketDataSource
