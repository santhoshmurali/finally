"""Seed prices and per-ticker parameters for the market simulator."""

import zlib

# Realistic starting prices for the default watchlist (as of project creation).
# The seed price doubles as the previous close (PLAN §6).
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
    # Indian (NSE) profile: plausible INR prices for the Dhan-mode watchlist
    "RELIANCE": 2900.0,
    "TCS": 3900.0,
    "INFY": 1500.0,
    "HDFCBANK": 1600.0,
    "ICICIBANK": 1100.0,
    "SBIN": 780.0,
    "BHARTIARTL": 1300.0,
    "ITC": 430.0,
    "LT": 3500.0,
    "HINDUNILVR": 2400.0,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = more price movement)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},  # Low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},  # Low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
    "RELIANCE": {"sigma": 0.24, "mu": 0.10},
    "TCS": {"sigma": 0.21, "mu": 0.10},
    "INFY": {"sigma": 0.24, "mu": 0.10},
    "HDFCBANK": {"sigma": 0.20, "mu": 0.10},
    "ICICIBANK": {"sigma": 0.22, "mu": 0.10},
    "SBIN": {"sigma": 0.28, "mu": 0.10},
    "BHARTIARTL": {"sigma": 0.24, "mu": 0.10},
    "ITC": {"sigma": 0.19, "mu": 0.08},
    "LT": {"sigma": 0.25, "mu": 0.10},
    "HINDUNILVR": {"sigma": 0.17, "mu": 0.07},
}

# Default parameters for tickers not in the list above (dynamically added)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Correlation groups for the simulator's Cholesky decomposition
# Tickers in the same group have higher intra-group correlation
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
    "in_it": {"TCS", "INFY"},
    "in_banks": {"HDFCBANK", "ICICIBANK", "SBIN"},
}

# Correlation coefficients
INTRA_TECH_CORR = 0.6  # Tech stocks move together
INTRA_FINANCE_CORR = 0.5  # Finance stocks move together
CROSS_GROUP_CORR = 0.3  # Between sectors / unknown tickers
TSLA_CORR = 0.3  # TSLA does its own thing

# Intra-group correlation per group name
GROUP_CORR: dict[str, float] = {
    "tech": INTRA_TECH_CORR,
    "finance": INTRA_FINANCE_CORR,
    "in_it": 0.65,
    "in_banks": 0.6,
}

US_DEFAULTS: list[str] = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
]  # fmt: skip
NSE_DEFAULTS: list[str] = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
    "BHARTIARTL", "ITC", "LT", "HINDUNILVR",
]  # fmt: skip

# What the simulator accepts as a ticker (letters/digits and . & - ; e.g. BRK.B, M&M, PYPL)
TICKER_PATTERN = r"[A-Z][A-Z0-9.&-]{0,14}"


def derived_seed_price(ticker: str) -> float:
    """Stable pseudo-random price in [50, 300) derived from the symbol alone."""
    h = zlib.crc32(ticker.upper().encode())
    return round(50 + (h % 25_000) / 100, 2)
