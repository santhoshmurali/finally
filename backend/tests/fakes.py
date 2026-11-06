"""Test doubles shared by the service and API tests."""

from app.market import MarketDataSource, PriceCache, UnsupportedTickerError


class FakeSource(MarketDataSource):
    """A scripted price source. `add_ticker` prices a ticker from `prices`.

    Records every add and remove so tests can check the priced set.
    """

    def __init__(self, cache: PriceCache, prices: dict[str, float]) -> None:
        super().__init__(cache)
        self.prices = prices
        self.added: list[str] = []
        self.removed: list[str] = []

    async def start(self, tickers: list[str]) -> None:
        for ticker in tickers:
            self.cache.update(ticker, self.prices[ticker])

    async def stop(self) -> None:
        return None

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self.prices:
            raise UnsupportedTickerError(ticker)
        self.added.append(ticker)
        self.cache.update(ticker, self.prices[ticker])

    async def remove_ticker(self, ticker: str) -> None:
        self.removed.append(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(ticker for ticker in self.prices if ticker in self.cache)

    async def daily_bars(self, ticker, start, end):
        return []

    def healthy(self) -> bool:
        return True
