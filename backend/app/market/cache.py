"""In-memory price cache: the single hand-off between price sources and consumers."""

from __future__ import annotations

from threading import Lock

from .models import PriceUpdate, now


class PriceCache:
    """Latest `PriceUpdate` per ticker. Sources write, SSE and trades read.

    `version` increases on every write so streamers can skip unchanged ticks.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        previous_close: float | None = None,
    ) -> PriceUpdate:
        """Record a new price. The first price for a ticker is its own previous tick."""
        with self._lock:
            old = self._prices.get(ticker)
            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=old.price if old else round(price, 2),
                previous_close=_pick_close(old, previous_close, price),
                timestamp=timestamp if timestamp is not None else now(),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def set_previous_close(self, ticker: str, previous_close: float) -> None:
        """Set the prior session close; recomputes the day change of a cached price."""
        with self._lock:
            old = self._prices.get(ticker)
            if old is None:
                return
            self._prices[ticker] = PriceUpdate(
                ticker, old.price, old.previous_price, round(previous_close, 2), old.timestamp
            )
            self._version += 1

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self._prices.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot copy of every cached price."""
        with self._lock:
            return dict(self._prices)

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    def __len__(self) -> int:
        return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._prices


def _pick_close(old: PriceUpdate | None, given: float | None, price: float) -> float:
    """Explicit close wins, then the carried-forward one, else the price itself."""
    if given is not None:
        return round(given, 2)
    if old is not None:
        return old.previous_close
    return round(price, 2)
