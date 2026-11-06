"""Keeps the market source's priced set in line with the watchlist and holdings."""

from __future__ import annotations

from app.market import MarketDataSource
from app.repository import read_position, read_positions, read_watchlist_tickers
from db import Database


def priced_tickers(db: Database) -> list[str]:
    """Watched plus held tickers: everything the source must price at startup."""
    with db.connect() as conn:
        watched = read_watchlist_tickers(conn)
        held = [row["ticker"] for row in read_positions(conn)]
    return sorted(set(watched) | set(held))


async def release_if_unused(db: Database, source: MarketDataSource, ticker: str) -> None:
    """Stop pricing `ticker` when it is neither watched nor held."""
    with db.connect() as conn:
        held = read_position(conn, ticker) is not None
        watched = ticker in read_watchlist_tickers(conn)
    if not held and not watched:
        await source.remove_ticker(ticker)
