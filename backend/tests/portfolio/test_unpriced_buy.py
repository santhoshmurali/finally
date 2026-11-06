"""A first buy on an unwatched ticker waits for the feed's first price instead of failing."""

import asyncio

import pytest

from app.market import PriceCache
from app.portfolio import PortfolioService, TradeRejectedError
from db import Database
from tests.fakes import FakeSource

PRICES = {"WIPRO": 200.0}


class LateFirstTickSource(FakeSource):
    """Like Dhan: the price arrives a moment after the subscribe call returns."""

    def __init__(self, cache: PriceCache, prices: dict[str, float], delay: float) -> None:
        super().__init__(cache, prices)
        self.delay = delay

    async def add_ticker(self, ticker: str) -> None:
        self.added.append(ticker)
        asyncio.get_running_loop().call_later(
            self.delay, self.cache.update, ticker, self.prices[ticker]
        )


class NeverPricedSource(FakeSource):
    async def add_ticker(self, ticker: str) -> None:
        self.added.append(ticker)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "finally.db", ("TCS",))


async def test_buy_waits_for_first_tick_then_fills(db):
    cache = PriceCache()
    source = LateFirstTickSource(cache, PRICES, delay=0.3)
    service = PortfolioService(db, cache, source)

    result = await service.execute_trade("WIPRO", 2, "buy")

    assert result.price == 200.0
    assert source.removed == []
    assert service.get_portfolio().positions[0].ticker == "WIPRO"


async def test_buy_is_rejected_after_the_wait_and_subscription_is_released(db):
    cache = PriceCache()
    source = NeverPricedSource(cache, PRICES)
    service = PortfolioService(db, cache, source, price_wait_seconds=0.3)

    with pytest.raises(TradeRejectedError, match="not priced yet"):
        await service.execute_trade("WIPRO", 1, "buy")

    assert source.added == ["WIPRO"]
    assert source.removed == ["WIPRO"]
    assert service.get_portfolio().positions == []
