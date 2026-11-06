"""Market-order execution, portfolio valuation and value snapshots."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.market import MarketDataSource, PriceCache
from app.priced_set import release_if_unused
from app.repository import (
    delete_position,
    insert_snapshot,
    insert_trade,
    read_cash,
    read_position,
    read_positions,
    read_snapshots,
    write_cash,
    write_position,
)
from db import Database

EPSILON = 1e-9
PRICE_WAIT_SECONDS = 5.0
PRICE_POLL_SECONDS = 0.1
Side = Literal["buy", "sell"]
SIDES: tuple[str, ...] = ("buy", "sell")


class TradeRejectedError(Exception):
    """A trade failed validation: bad input, insufficient cash or shares, or no price."""


@dataclass(frozen=True, slots=True)
class TradeResult:
    ticker: str
    side: Side
    quantity: float
    price: float
    executed_at: str
    cash_balance: float


@dataclass(frozen=True, slots=True)
class PositionView:
    ticker: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float
    day_change_percent: float


@dataclass(frozen=True, slots=True)
class PortfolioView:
    cash_balance: float
    positions: list[PositionView]
    positions_value: float
    total_value: float
    unrealized_pnl: float


class PortfolioService:
    """Executes market orders against the price cache and values the portfolio.

    A position without a live price is valued at its average cost, so the total
    stays defined before the first tick arrives.
    """

    def __init__(
        self,
        db: Database,
        cache: PriceCache,
        source: MarketDataSource,
        price_wait_seconds: float = PRICE_WAIT_SECONDS,
    ) -> None:
        self.db = db
        self.cache = cache
        self.source = source
        self.price_wait_seconds = price_wait_seconds

    async def execute_trade(self, ticker: str, quantity: float, side: str) -> TradeResult:
        """Fill a market order at the current cached price and record it."""
        symbol = ticker.strip().upper()
        validate_order(quantity, side)
        if side == "buy" and symbol not in self.cache:
            await self.source.add_ticker(symbol)
            await self._wait_for_price(symbol)
        try:
            return self._fill(symbol, quantity, side)
        finally:
            await release_if_unused(self.db, self.source, symbol)

    async def _wait_for_price(self, symbol: str) -> None:
        """Give a newly subscribed ticker time to deliver its first price.

        The first tick usually lands about a second after subscribing. Rejecting
        at once would make the cleanup unsubscribe before that tick arrives.
        """
        deadline = time.monotonic() + self.price_wait_seconds
        while self.cache.get_price(symbol) is None and time.monotonic() < deadline:
            await asyncio.sleep(PRICE_POLL_SECONDS)

    def get_portfolio(self) -> PortfolioView:
        with self.db.connect() as conn:
            cash = read_cash(conn)
            rows = read_positions(conn)
        positions = [self._value_position(row) for row in rows]
        positions_value = sum(p.market_value for p in positions)
        return PortfolioView(
            cash_balance=cash,
            positions=positions,
            positions_value=positions_value,
            total_value=cash + positions_value,
            unrealized_pnl=sum(p.unrealized_pnl for p in positions),
        )

    def record_snapshot(self) -> float:
        """Store the current total value and return it."""
        with self.db.connect() as conn:
            return self._snapshot(conn)

    def history(self, since: datetime | None = None, limit: int | None = None) -> list[dict]:
        """Snapshots oldest first, optionally limited to a time window and row count."""
        since_iso = since.isoformat(timespec="microseconds") if since is not None else None
        with self.db.connect() as conn:
            rows = read_snapshots(conn, since_iso, limit)
        return [
            {"total_value": row["total_value"], "recorded_at": row["recorded_at"]} for row in rows
        ]

    def _fill(self, symbol: str, quantity: float, side: str) -> TradeResult:
        price = self.cache.get_price(symbol)
        if price is None:
            raise TradeRejectedError(f"{symbol} is not priced yet; try again in a moment")
        with self.db.connect() as conn:
            if side == "buy":
                result = self._buy(conn, symbol, quantity, price)
            else:
                result = self._sell(conn, symbol, quantity, price)
            self._snapshot(conn)
        return result

    def _buy(
        self, conn: sqlite3.Connection, symbol: str, quantity: float, price: float
    ) -> TradeResult:
        cash = read_cash(conn)
        cost = quantity * price
        if cost > cash + EPSILON:
            raise TradeRejectedError(
                f"insufficient cash: buying {quantity:g} {symbol} costs {cost:,.2f}, "
                f"cash is {cash:,.2f}"
            )
        held = read_position(conn, symbol)
        held_quantity = held["quantity"] if held else 0.0
        held_cost = held["avg_cost"] * held_quantity if held else 0.0
        new_quantity = held_quantity + quantity
        write_position(conn, symbol, new_quantity, (held_cost + cost) / new_quantity)
        write_cash(conn, cash - cost)
        executed_at = insert_trade(conn, symbol, "buy", quantity, price)
        return TradeResult(symbol, "buy", quantity, price, executed_at, cash - cost)

    def _sell(
        self, conn: sqlite3.Connection, symbol: str, quantity: float, price: float
    ) -> TradeResult:
        held = read_position(conn, symbol)
        held_quantity = held["quantity"] if held else 0.0
        if quantity > held_quantity + EPSILON:
            raise TradeRejectedError(
                f"insufficient shares: holding {held_quantity:g} {symbol}, selling {quantity:g}"
            )
        remaining = held_quantity - quantity
        if remaining <= EPSILON:
            delete_position(conn, symbol)
        else:
            write_position(conn, symbol, remaining, held["avg_cost"])
        cash = read_cash(conn) + quantity * price
        write_cash(conn, cash)
        executed_at = insert_trade(conn, symbol, "sell", quantity, price)
        return TradeResult(symbol, "sell", quantity, price, executed_at, cash)

    def _snapshot(self, conn: sqlite3.Connection) -> float:
        cash = read_cash(conn)
        positions_value = sum(
            self._value_position(row).market_value for row in read_positions(conn)
        )
        total = cash + positions_value
        insert_snapshot(conn, total)
        return total

    def _value_position(self, row: sqlite3.Row) -> PositionView:
        quantity = row["quantity"]
        avg_cost = row["avg_cost"]
        update = self.cache.get(row["ticker"])
        price = update.price if update else avg_cost
        cost_basis = quantity * avg_cost
        market_value = quantity * price
        unrealized = market_value - cost_basis
        return PositionView(
            ticker=row["ticker"],
            quantity=quantity,
            avg_cost=avg_cost,
            current_price=price,
            market_value=market_value,
            unrealized_pnl=unrealized,
            unrealized_pnl_percent=(unrealized / cost_basis * 100) if cost_basis else 0.0,
            day_change_percent=update.day_change_percent if update else 0.0,
        )


def validate_order(quantity: float, side: str) -> None:
    """Reject a non-positive or non-finite quantity and an unknown side."""
    if side not in SIDES:
        raise TradeRejectedError(f"side must be 'buy' or 'sell', got {side!r}")
    if not (quantity > 0 and quantity != float("inf")):
        raise TradeRejectedError("quantity must be a positive number")


def history_window(range_name: str, now: datetime | None = None) -> datetime | None:
    """Start time for a named window: `1h`, `1d`, `7d`, or `all` (no limit)."""
    windows = {"1h": timedelta(hours=1), "1d": timedelta(days=1), "7d": timedelta(days=7)}
    if range_name == "all":
        return None
    if range_name not in windows:
        raise ValueError(f"range must be one of 1h, 1d, 7d, all; got {range_name!r}")
    current = now or datetime.now(UTC)
    return current - windows[range_name]
