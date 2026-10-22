"""Deterministic synthetic daily bars for the simulator."""

from __future__ import annotations

import math
import zlib
from datetime import date, timedelta

import numpy as np

from .models import Bar

DAYS_PER_YEAR = 252
HISTORY_LOOKBACK_DAYS = 365  # weekdays generated per request; callers slice


def weekdays_ending_at(end: date, n: int) -> list[date]:
    """The n weekday dates ending at ``end`` (rolled back if a weekend), ascending."""
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def last_trading_day_before(d: date) -> date:
    """Most recent weekday strictly before ``d``."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def synth_daily_bars(
    ticker: str,
    end: date,
    n: int,
    anchor_price: float,
    *,
    mu: float = 0.05,
    sigma: float = 0.25,
) -> list[Bar]:
    """Deterministic daily OHLCV bars; the last bar's close equals ``anchor_price``."""
    if n <= 0:
        return []
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    sigma_d = sigma / math.sqrt(DAYS_PER_YEAR)
    r = (mu - 0.5 * sigma**2) / DAYS_PER_YEAR + sigma_d * rng.standard_normal(n)
    cum = np.cumsum(r)
    closes = anchor_price * np.exp(cum - cum[-1])
    gaps = np.exp(rng.normal(0.0, 0.25 * sigma_d, n))
    opens = np.concatenate(([closes[0]], closes[:-1])) * gaps
    opens[0] = closes[0]
    wick_hi = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    wick_lo = np.abs(rng.normal(0.0, 0.5 * sigma_d, n))
    highs = np.maximum(opens, closes) * (1 + wick_hi)
    lows = np.minimum(opens, closes) * (1 - wick_lo)
    base_vol = 500_000 + (zlib.crc32(ticker[::-1].encode()) % 9_500_000)
    vols = base_vol * np.exp(rng.normal(0.0, 0.3, n)) * (1 + 20 * np.abs(r))
    return [
        Bar(
            d,
            round(float(o), 2),
            round(float(h), 2),
            round(float(lo), 2),
            round(float(c), 2),
            int(v),
        )
        for d, o, h, lo, c, v in zip(
            weekdays_ending_at(end, n), opens, highs, lows, closes, vols, strict=True
        )
    ]
