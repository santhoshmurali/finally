"""Market data errors. One hierarchy so callers never see library exceptions."""


class MarketDataError(Exception):
    """Base class for every market data failure."""


class UnsupportedTickerError(MarketDataError):
    """The ticker is not tradable on the active source (unknown symbol)."""


class AuthenticationError(MarketDataError):
    """Credentials are missing, invalid, expired or lack a Data API plan. Not retryable."""


class RateLimitError(MarketDataError):
    """The provider throttled us. Retry later with backoff."""


class DataUnavailableError(MarketDataError):
    """The provider could not serve the request (network, 5xx, malformed reply)."""
