"""Watchlist add, remove and listing rules."""

import pytest

from app.market import PriceCache, UnsupportedTickerError
from app.portfolio import PortfolioService
from app.watchlist import AlreadyWatchedError, InvalidTickerError, NotWatchedError, WatchlistService
from db import Database
from tests.fakes import FakeSource

WATCHLIST = ("TCS", "INFY")
PRICES = {"TCS": 100.0, "INFY": 50.0, "WIPRO": 30.0, "RELIANCE": 200.0}


@pytest.fixture
async def setup(tmp_path):
    cache = PriceCache()
    db = Database(tmp_path / "finally.db", WATCHLIST)
    source = FakeSource(cache, PRICES)
    await source.start(list(WATCHLIST))
    watchlist = WatchlistService(db, cache, source)
    portfolio = PortfolioService(db, cache, source)
    return watchlist, portfolio, source, cache


async def test_list_shows_default_tickers_with_prices(setup):
    watchlist, _, _, _ = setup

    entries = {entry.ticker: entry for entry in watchlist.list_tickers()}

    assert set(entries) == set(WATCHLIST)
    assert entries["TCS"].price == 100.0


async def test_add_normalizes_symbol_prices_it_and_persists(setup):
    watchlist, _, source, cache = setup

    entry = await watchlist.add("  wipro ")

    assert entry.ticker == "WIPRO"
    assert entry.price == 30.0
    assert source.added == ["WIPRO"]
    assert "WIPRO" in cache
    assert "WIPRO" in {e.ticker for e in watchlist.list_tickers()}


async def test_adding_duplicate_is_rejected(setup):
    watchlist, _, _, _ = setup

    with pytest.raises(AlreadyWatchedError):
        await watchlist.add("TCS")


async def test_unsupported_ticker_is_rejected_and_not_stored(setup):
    watchlist, _, _, _ = setup

    with pytest.raises(UnsupportedTickerError):
        await watchlist.add("NOTREAL")

    assert "NOTREAL" not in {e.ticker for e in watchlist.list_tickers()}


@pytest.mark.parametrize("text", ["", "TC S", "../etc", "A" * 21])
async def test_malformed_ticker_is_rejected(setup, text):
    watchlist, _, _, _ = setup

    with pytest.raises(InvalidTickerError):
        await watchlist.add(text)


async def test_remove_stops_pricing_when_not_held(setup):
    watchlist, _, source, cache = setup

    await watchlist.remove("INFY")

    assert "INFY" not in {e.ticker for e in watchlist.list_tickers()}
    assert source.removed == ["INFY"]
    assert "INFY" not in cache


async def test_remove_keeps_pricing_held_ticker(setup):
    watchlist, portfolio, source, cache = setup
    await portfolio.execute_trade("INFY", 1, "buy")

    await watchlist.remove("INFY")

    assert source.removed == []
    assert "INFY" in cache


async def test_removing_unwatched_ticker_is_rejected(setup):
    watchlist, _, _, _ = setup

    with pytest.raises(NotWatchedError):
        await watchlist.remove("WIPRO")
