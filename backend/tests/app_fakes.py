"""Deterministic market source for app tests: prices hold still until a test changes them."""

from datetime import date

from app.market import DEFAULT_WATCHLIST, Bar, MarketDataSource, PriceCache, UnsupportedTickerError

PRICES: dict[str, float | None] = {
    **dict.fromkeys(DEFAULT_WATCHLIST, 1000.0),
    "TCS": 2500.0,
    "WIPRO": 400.0,
    "SILENT": None,
}


class FixedPriceSource(MarketDataSource):
    """Knows only the tickers in `prices`. A `None` price is subscribed but not priced yet."""

    def __init__(self, cache: PriceCache, prices: dict[str, float | None] = PRICES) -> None:
        super().__init__(cache)
        self._prices = prices
        self._tickers: list[str] = []

    async def start(self, tickers: list[str]) -> None:
        for ticker in tickers:
            await self.add_ticker(ticker)

    async def stop(self) -> None:
        """Nothing runs in the background."""

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            raise UnsupportedTickerError(f"{ticker} is not supported")
        if ticker in self._tickers:
            return
        self._tickers.append(ticker)
        price = self._prices[ticker]
        if price is not None:
            self.cache.update(ticker, price, previous_close=price)

    async def remove_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            self._tickers.remove(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        return []

    def healthy(self) -> bool:
        return True
