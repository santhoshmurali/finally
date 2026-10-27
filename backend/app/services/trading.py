"""Market orders: each buy or sell fills at the cached price in one transaction."""

import sqlite3

from app.services.errors import PriceUnavailableError, RejectedError
from app.services.priced import release_if_unused, track_ticker
from app.services.snapshots import record_snapshot
from app.state import AppState
from db.connection import transaction
from db.models import Trade
from db.positions import delete_position, get_position, save_position
from db.profile import get_cash_balance, set_cash_balance
from db.trades import insert_trade

SHARE_EPSILON = 1e-9


async def execute_trade(state: AppState, ticker: str, quantity: float, side: str) -> Trade:
    """Fill a market order at the current price. Raises `ServiceError` when it cannot fill."""
    ticker = ticker.upper()
    if quantity <= 0:
        raise RejectedError("Quantity must be greater than zero")
    await track_ticker(state, ticker)
    try:
        trade = _fill(state, ticker, quantity, side)
    finally:
        await release_if_unused(state, ticker)
    record_snapshot(state)
    return trade


def _fill(state: AppState, ticker: str, quantity: float, side: str) -> Trade:
    price = state.cache.get_price(ticker)
    if price is None:
        raise PriceUnavailableError(f"No price yet for {ticker}; try again shortly")
    with transaction() as conn:
        if side == "buy":
            _buy(conn, ticker, quantity, price)
        else:
            _sell(conn, ticker, quantity, price)
        return insert_trade(conn, ticker, side, quantity, price)


def _buy(conn: sqlite3.Connection, ticker: str, quantity: float, price: float) -> None:
    cash = get_cash_balance(conn)
    cost = round(quantity * price, 2)
    if cost > cash:
        raise RejectedError(f"Insufficient cash: need ₹{cost:,.2f}, have ₹{cash:,.2f}")
    held = get_position(conn, ticker)
    if held is None:
        save_position(conn, ticker, quantity, price)
    else:
        total_quantity = held.quantity + quantity
        avg_cost = (held.quantity * held.avg_cost + cost) / total_quantity
        save_position(conn, ticker, total_quantity, avg_cost)
    set_cash_balance(conn, round(cash - cost, 2))


def _sell(conn: sqlite3.Connection, ticker: str, quantity: float, price: float) -> None:
    held = get_position(conn, ticker)
    held_quantity = held.quantity if held else 0.0
    if quantity > held_quantity:
        raise RejectedError(f"Insufficient shares: hold {held_quantity:g}, selling {quantity:g}")
    remaining = held_quantity - quantity
    if remaining < SHARE_EPSILON:
        delete_position(conn, ticker)
    else:
        save_position(conn, ticker, remaining, held.avg_cost)
    proceeds = round(quantity * price, 2)
    set_cash_balance(conn, round(get_cash_balance(conn) + proceeds, 2))
