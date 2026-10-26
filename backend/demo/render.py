"""Pure rendering helpers for the console demo: charts, rows, table text, commands."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from app.market import PriceUpdate

BLOCKS = "▁▂▃▄▅▆▇█"
MIN_RANGE_PERCENT = 0.05  # a window that moved less than this looks flat, not like noise

Fragments = list[tuple[str, str]]
QUIT_WORDS = {"q", "quit", "exit"}
REMOVE_WORDS = {"rm", "remove", "del", "delete"}
ADD_WORDS = {"add", "a"}


def sparkline(values: list[float], width: int) -> str:
    """One text row charting the last `width` values, newest on the right.

    The vertical scale spans the window's low to high, widened to at least
    MIN_RANGE_PERCENT of the price so a single tick does not look like a crash.
    Short histories are right-aligned so the line streams in from the right.
    """
    values = values[-width:]
    if not values:
        return " " * width
    low, high = min(values), max(values)
    span = max(high - low, values[-1] * MIN_RANGE_PERCENT / 100) or 1.0
    base = (low + high) / 2 - span / 2
    levels = len(BLOCKS)
    chars = [BLOCKS[max(0, min(int((v - base) / span * levels), levels - 1))] for v in values]
    return "".join(chars).rjust(width)


class PriceHistory:
    """Fixed-size window of sampled prices per symbol."""

    def __init__(self, window: int) -> None:
        self._window = window
        self._series: dict[str, deque[float]] = {}

    def sample(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            self._series.setdefault(symbol, deque(maxlen=self._window)).append(price)

    def series(self, symbol: str) -> list[float]:
        return list(self._series.get(symbol, []))

    def drop(self, symbol: str) -> None:
        self._series.pop(symbol, None)


@dataclass(frozen=True)
class Row:
    """One display line. Price fields are None until the first tick arrives."""

    symbol: str
    price: float | None
    day_percent: float | None
    direction: str
    updated: float | None
    chart: str
    trend_up: bool


def build_rows(
    symbols: list[str], prices: dict[str, PriceUpdate], history: PriceHistory, width: int
) -> list[Row]:
    rows = []
    for symbol in symbols:
        update = prices.get(symbol)
        series = history.series(symbol)
        rows.append(Row(
            symbol=symbol,
            price=update.price if update else None,
            day_percent=update.day_change_percent if update else None,
            direction=update.direction if update else "flat",
            updated=update.timestamp if update else None,
            chart=sparkline(series, width),
            trend_up=len(series) < 2 or series[-1] >= series[0],
        ))
    return rows


def table_fragments(rows: list[Row], width: int, window_seconds: float) -> Fragments:
    """Styled text for the table; styles are prompt_toolkit class names."""
    chart_title = f"CHART (last {window_seconds:g}s)"
    out: Fragments = [("class:header", f" {'SYMBOL':<12}{'LTP':>11}{'CHG %':>11}  {'UPDATED':<9} "
                                       f"{chart_title:<{width}}\n")]
    for row in rows:
        out += _row_fragments(row)
    return out


def _row_fragments(row: Row) -> Fragments:
    if row.price is None:
        return [("class:dim", f" {row.symbol:<12}waiting for first tick...\n")]
    arrow = "▲" if row.day_percent >= 0 else "▼"
    change = f"{arrow} {row.day_percent:+.2f}%"
    trend = "class:up" if row.day_percent >= 0 else "class:down"
    tick = {"up": "class:tick-up", "down": "class:tick-down"}.get(row.direction, "")
    updated = datetime.fromtimestamp(row.updated).strftime("%H:%M:%S")
    return [
        ("", f" {row.symbol:<12}"),
        (tick, f"{row.price:>11,.2f}"),
        (trend, f"{change:>11}"),
        ("class:dim", f"  {updated:<9} "),
        ("class:up" if row.trend_up else "class:down", f"{row.chart}\n"),
    ]


def plain_text(fragments: Fragments) -> str:
    """Drop styles, for headless output."""
    return "".join(text for _, text in fragments)


@dataclass(frozen=True)
class Command:
    action: str  # add | remove | quit | error
    symbol: str = ""


def parse_command(text: str) -> Command | None:
    """`add X`, `rm X`, `quit`, or just a symbol (adds it). Blank input gives None."""
    words = text.split()
    if not words:
        return None
    head = words[0].lower()
    if head in QUIT_WORDS and len(words) == 1:
        return Command("quit")
    if head in REMOVE_WORDS and len(words) == 2:
        return Command("remove", words[1].upper())
    if head in ADD_WORDS and len(words) == 2:
        return Command("add", words[1].upper())
    if len(words) == 1 and head not in REMOVE_WORDS | ADD_WORDS:
        return Command("add", words[0].upper())
    return Command("error", text.strip())
