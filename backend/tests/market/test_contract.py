"""Contract suite: every MarketDataSource answers the unified API the same way."""

from datetime import date, datetime, timedelta

import pytest

from app.market.cache import PriceCache
from app.market.dhan.client import IST
from app.market.dhan.instruments import InstrumentResolver
from app.market.dhan.source import DhanDataSource
from app.market.interface import MarketDataSource
from app.market.simulator import SimulatorDataSource

from .test_dhan_source import CSV_TEXT, FakeClient, bar


def _dhan(tmp_path) -> DhanDataSource:
    today = datetime.now(IST).date()
    client = FakeClient()
    client.prices = {11536: 3900.0, 2885: 2900.0, 1594: 1500.0}
    client.history = {
        11536: [bar(today - timedelta(days=d), 3800.0 + d) for d in (6, 5, 4, 3, 2)],
        2885: [bar(today - timedelta(days=2), 2880.0)],
    }
    (tmp_path / "dhan-nse-eq-instruments.csv").write_text(CSV_TEXT)
    return DhanDataSource(
        "cid", "tok", PriceCache(), tmp_path, client=client, resolver=InstrumentResolver(tmp_path)
    )


@pytest.fixture(params=["simulator", "dhan"])
async def source(request, tmp_path) -> MarketDataSource:
    if request.param == "simulator":
        s = SimulatorDataSource(PriceCache(), update_interval=0.05, seed=1)
    else:
        s = _dhan(tmp_path)
    await s.start(["TCS", "RELIANCE"])
    yield s
    await s.stop()


async def test_metadata(source):
    assert source.name in {"simulator", "dhanhq"}
    assert len(source.currency) == 3


async def test_tracks_started_tickers(source):
    assert sorted(source.get_tickers()) == ["RELIANCE", "TCS"]


async def test_is_supported(source):
    assert await source.is_supported("TCS")
    assert not await source.is_supported("")
    assert not await source.is_supported("???")


async def test_quotes_are_positive_and_keyed_by_uppercase_ticker(source):
    quotes = await source.get_quotes(["tcs", "RELIANCE"])
    assert set(quotes) == {"TCS", "RELIANCE"}
    assert all(q.price > 0 for q in quotes.values())
    assert all(q.ticker == t for t, q in quotes.items())


async def test_quotes_omit_unsupported(source):
    quotes = await source.get_quotes(["TCS", "???"])
    assert "???" not in quotes


async def test_daily_bars_ascending_and_in_range(source):
    start, end = date.today() - timedelta(days=20), date.today()
    bars = await source.get_daily_bars("TCS", start, end)
    assert bars
    assert [b.date for b in bars] == sorted(b.date for b in bars)
    assert all(start <= b.date <= end for b in bars)
    assert all(b.close > 0 and b.volume >= 0 for b in bars)


async def test_daily_bars_unsupported_ticker_is_empty(source):
    assert await source.get_daily_bars("???", date(2026, 1, 1), date.today()) == []


async def test_eod_closes_are_positive_and_omit_unknown(source):
    closes = await source.get_eod_closes(["TCS", "???"])
    assert set(closes) == {"TCS"}
    assert closes["TCS"] > 0


async def test_add_and_remove_ticker(source):
    await source.add_ticker("INFY")
    assert "INFY" in source.get_tickers()
    await source.add_ticker("INFY")  # idempotent
    assert source.get_tickers().count("INFY") == 1
    await source.remove_ticker("INFY")
    assert "INFY" not in source.get_tickers()
    await source.remove_ticker("INFY")  # no-op
