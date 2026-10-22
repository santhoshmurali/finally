"""Simulator market knowledge as data: NSE seed prices, volatility and correlation groups."""

import re
import zlib

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "LT", "HINDUNILVR",
]

# INR prices from the NSE close of 2026-10-21. A seed price doubles as the previous close.
SEED_PRICES: dict[str, float] = {
    "RELIANCE": 1209.00,
    "TCS": 2529.00,
    "INFY": 1168.00,
    "HDFCBANK": 706.95,
    "ICICIBANK": 1385.00,
    "SBIN": 963.00,
    "BHARTIARTL": 1891.70,
    "ITC": 262.00,
    "LT": 3636.00,
    "HINDUNILVR": 1850.20,
    "WIPRO": 189.17,
}

# sigma: annualised volatility, mu: annualised drift.
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "RELIANCE": {"sigma": 0.24, "mu": 0.06},
    "TCS": {"sigma": 0.22, "mu": 0.06},
    "INFY": {"sigma": 0.26, "mu": 0.05},
    "HDFCBANK": {"sigma": 0.20, "mu": 0.07},
    "ICICIBANK": {"sigma": 0.24, "mu": 0.08},
    "SBIN": {"sigma": 0.30, "mu": 0.08},
    "BHARTIARTL": {"sigma": 0.25, "mu": 0.09},
    "ITC": {"sigma": 0.19, "mu": 0.06},
    "LT": {"sigma": 0.25, "mu": 0.08},
    "HINDUNILVR": {"sigma": 0.18, "mu": 0.04},
    "WIPRO": {"sigma": 0.27, "mu": 0.04},
}
DEFAULT_PARAMS = {"sigma": 0.28, "mu": 0.05}

CORRELATION_GROUPS: dict[str, set[str]] = {
    "it": {"TCS", "INFY", "WIPRO"},
    "banks": {"HDFCBANK", "ICICIBANK", "SBIN"},
    "consumer": {"ITC", "HINDUNILVR"},
}
INTRA_GROUP_CORRELATION = 0.6
CROSS_GROUP_CORRELATION = 0.3

# What the simulator accepts as a ticker: letters, digits and . & - (for example M&M, BAJAJ-AUTO).
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&.\-]{0,19}$")
UNKNOWN_SEED_RANGE = (100.0, 3000.0)


def seed_price_for(ticker: str) -> float:
    """Seed price of `ticker`; unknown tickers get a stable price derived from the symbol."""
    if ticker in SEED_PRICES:
        return SEED_PRICES[ticker]
    low, high = UNKNOWN_SEED_RANGE
    return round(low + zlib.crc32(ticker.encode()) % 100_000 / 100_000 * (high - low), 2)
