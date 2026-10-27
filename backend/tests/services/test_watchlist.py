"""Watchlist service: membership rules and how it keeps the priced set in step."""

import pytest

from app.market import DEFAULT_WATCHLIST
from app.services.errors import NotFoundError, RejectedError
from app.services.trading import execute_trade
from app.services.watchlist import add_to_watchlist, list_watchlist, remove_from_watchlist


def test_default_watchlist_is_listed_without_prices_until_priced(state):
    views = list_watchlist(state)

    assert [view.ticker for view in views] == list(DEFAULT_WATCHLIST)
    assert all(view.price is None and view.day_change_percent is None for view in views)


async def test_add_normalises_the_ticker_and_prices_it(state):
    entry = await add_to_watchlist(state, "wipro")

    assert entry.ticker == "WIPRO"
    assert "WIPRO" in state.cache
    wipro = next(view for view in list_watchlist(state) if view.ticker == "WIPRO")
    assert wipro.price == 400.0


async def test_duplicate_is_rejected(state):
    with pytest.raises(RejectedError, match="already on the watchlist"):
        await add_to_watchlist(state, "TCS")


async def test_unsupported_ticker_is_rejected(state):
    with pytest.raises(RejectedError, match="not supported"):
        await add_to_watchlist(state, "NOPE")


async def test_removing_an_absent_ticker_is_not_found(state):
    with pytest.raises(NotFoundError) as error:
        await remove_from_watchlist(state, "WIPRO")

    assert error.value.status_code == 404


async def test_removing_a_held_ticker_keeps_it_priced(state):
    await add_to_watchlist(state, "WIPRO")
    await execute_trade(state, "WIPRO", 1, "buy")

    await remove_from_watchlist(state, "WIPRO")

    assert "WIPRO" in state.cache
