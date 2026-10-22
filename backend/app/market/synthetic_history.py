"""Deterministic synthetic daily bars for the simulator (no network, same input -> same bars)."""

from __future__ import annotations

import math
import random
import zlib
from datetime import date, timedelta

from .models import Bar

DAILY_SIGMA = 0.015


def synthetic_bars(
    ticker: str, start: date, end: date, anchor_price: float, today: date | None = None
) -> list[Bar]:
    """Completed weekday bars in `start..end`, oldest first.

    The last completed weekday before `today` closes at `anchor_price` (the
    simulator's previous close); earlier days walk backwards from it.
    """
    anchor_day = _previous_weekday(today or date.today())
    last_day = min(end, anchor_day)
    first_day = max(start, date(2000, 1, 1))
    if last_day < first_day:
        return []
    closes: dict[date, float] = {}
    close, day = anchor_price, anchor_day
    while day >= first_day:
        closes[day] = close
        previous_day = _previous_weekday(day)
        close = close / math.exp(_daily_return(ticker, day))
        day = previous_day
    closes[day] = close  # the session before the range, so the first open is range-independent
    return [_bar(ticker, d, closes) for d in sorted(closes) if first_day <= d <= last_day]


def _bar(ticker: str, day: date, closes: dict[date, float]) -> Bar:
    rng = random.Random(zlib.crc32(f"{ticker}:bar:{day.toordinal()}".encode()))
    close = closes[day]
    open_ = closes.get(_previous_weekday(day), close) * (1 + rng.uniform(-0.004, 0.004))
    high = max(open_, close) * (1 + rng.uniform(0, 0.008))
    low = min(open_, close) * (1 - rng.uniform(0, 0.008))
    return Bar(day, round(open_, 2), round(high, 2), round(low, 2), round(close, 2),
               rng.randint(200_000, 5_000_000))


def _daily_return(ticker: str, day: date) -> float:
    rng = random.Random(zlib.crc32(f"{ticker}:ret:{day.toordinal()}".encode()))
    return rng.gauss(0, DAILY_SIGMA)


def _previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day
