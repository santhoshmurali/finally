import pytest

from app.market import MarketDataSource, PriceCache, UnsupportedTickerError
from app.state import AppState
from db.connection import init_db

UNSUPPORTED_TICKER = "NOPE"


class FakeSource(MarketDataSource):
    """Market source that accepts every ticker except UNSUPPORTED_TICKER and never streams."""

    async def start(self, tickers: list[str]) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def add_ticker(self, ticker: str) -> None:
        if ticker == UNSUPPORTED_TICKER:
            raise UnsupportedTickerError(f"{ticker} is not supported")

    async def remove_ticker(self, ticker: str) -> None:
        return None

    def get_tickers(self) -> list[str]:
        return []

    async def daily_bars(self, ticker, start, end):
        return []

    def healthy(self) -> bool:
        return True


@pytest.fixture
def state(tmp_path, monkeypatch) -> AppState:
    """App state on a fresh seeded database, with TCS priced at 2500 and RELIANCE at 1200."""
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    monkeypatch.setenv("LLM_MOCK", "false")
    init_db()
    cache = PriceCache()
    cache.update("TCS", 2500.0)
    cache.update("RELIANCE", 1200.0)
    return AppState(cache=cache, source=FakeSource(cache))
