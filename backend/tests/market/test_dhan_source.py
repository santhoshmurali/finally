"""DhanDataSource end to end: fake socket -> feed -> cache, plus ticker management."""

import asyncio
import time
from datetime import date

import pytest

from app.market.cache import PriceCache
from app.market.dhan.auth import Credentials
from app.market.dhan.feed import DhanFeed
from app.market.dhan.instruments import InstrumentResolver
from app.market.dhan.source import DhanDataSource
from app.market.errors import UnsupportedTickerError
from app.market.models import Bar

from .dhan_fakes import FakeConnect, disconnect_bytes, prev_close_bytes, ticker_bytes

CREDENTIALS = Credentials("tok", "1100", time.time() + 3600)
CSV_TEXT = """EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,UNDERLYING_SYMBOL,SERIES
NSE,E,11536,EQUITY,TCS,EQ
NSE,E,2885,EQUITY,RELIANCE,EQ
NSE,E,1594,EQUITY,INFY,EQ
"""
BARS = [Bar(date(2026, 10, 21), 1, 2, 0.5, 1.5, 10)]


async def hang():
    await asyncio.Event().wait()


class FakeClient:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def daily_bars(self, security_id, start, end):
        self.calls.append((security_id, start, end))
        return BARS

    async def close(self):
        self.closed = True


async def until(condition, tries=200):
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")


@pytest.fixture
def parts():
    cache = PriceCache()
    client = FakeClient()
    resolver = InstrumentResolver.from_csv(CSV_TEXT)
    return cache, client, resolver


def build(parts, *sessions):
    cache, client, resolver = parts
    connect = FakeConnect(*sessions)
    source = DhanDataSource(cache, CREDENTIALS, resolver=resolver, client=client)
    source._feed = DhanFeed(CREDENTIALS, source._on_packet, connect=connect)
    return source, connect


async def test_live_packets_fill_the_cache(parts):
    cache = parts[0]
    session = [ticker_bytes(11536, 2506.9), prev_close_bytes(11536, 2529.0), hang]
    source, connect = build(parts, session)
    await source.start(["TCS", "RELIANCE"])
    await until(lambda: cache.get("TCS") and cache.get("TCS").previous_close == 2529.0)
    update = cache.get("TCS")
    assert update.price == 2506.9
    assert update.day_change == -22.1
    assert source.healthy()
    await source.stop()
    sent = connect.connections[0].sent[0]
    assert {i["SecurityId"] for i in sent["InstrumentList"]} == {"11536", "2885"}


async def test_previous_close_before_tick_is_applied(parts):
    cache = parts[0]
    source, _ = build(parts, [prev_close_bytes(2885, 1209.0), ticker_bytes(2885, 1184.5), hang])
    await source.start(["RELIANCE"])
    await until(lambda: cache.get("RELIANCE"))
    assert cache.get("RELIANCE").previous_close == 1209.0
    await source.stop()


async def test_second_tick_sets_previous_price(parts):
    cache = parts[0]
    source, _ = build(parts, [ticker_bytes(1594, 100.0), ticker_bytes(1594, 101.0), hang])
    await source.start(["INFY"])
    await until(lambda: cache.get("INFY") and cache.get("INFY").price == 101.0)
    assert cache.get("INFY").direction == "up"
    await source.stop()


async def test_packets_for_untracked_tickers_are_ignored(parts):
    cache = parts[0]
    source, _ = build(parts, [ticker_bytes(2885, 1.0), ticker_bytes(11536, 2.0), hang])
    await source.start(["TCS"])
    await until(lambda: "TCS" in cache)
    assert "RELIANCE" not in cache
    await source.stop()


async def test_unknown_ticker_fails_start_before_connecting(parts):
    source, connect = build(parts)
    with pytest.raises(UnsupportedTickerError):
        await source.start(["TCS", "AAPL"])
    assert connect.urls == []


async def test_add_ticker_subscribes_once(parts):
    source, connect = build(parts, [hang])
    await source.start(["TCS"])
    await until(lambda: connect.connections)
    await source.add_ticker("infy")
    await source.add_ticker("INFY")
    sent = connect.connections[0].sent
    assert [m["RequestCode"] for m in sent] == [15, 15]
    assert sent[1]["InstrumentList"][0]["SecurityId"] == "1594"
    assert source.get_tickers() == ["INFY", "TCS"]
    await source.stop()


async def test_add_unknown_ticker_raises(parts):
    source, _ = build(parts, [hang])
    await source.start(["TCS"])
    with pytest.raises(UnsupportedTickerError):
        await source.add_ticker("AAPL")
    assert source.get_tickers() == ["TCS"]
    await source.stop()


async def test_remove_ticker_unsubscribes_and_clears_cache(parts):
    cache = parts[0]
    source, connect = build(parts, [ticker_bytes(11536, 5.0), hang])
    await source.start(["TCS", "INFY"])
    await until(lambda: "TCS" in cache)
    await source.remove_ticker("TCS")
    await source.remove_ticker("TCS")
    assert "TCS" not in cache
    assert source.get_tickers() == ["INFY"]
    sent = connect.connections[0].sent
    assert [m["RequestCode"] for m in sent] == [15, 16]
    assert sent[1]["InstrumentList"][0]["SecurityId"] == "11536"
    await source.stop()


async def test_daily_bars_resolve_ticker(parts):
    _, client, _ = parts
    source, _ = build(parts)
    bars = await source.daily_bars("tcs", date(2026, 10, 1), date(2026, 10, 21))
    assert bars == BARS
    assert client.calls == [(11536, date(2026, 10, 1), date(2026, 10, 21))]
    with pytest.raises(UnsupportedTickerError):
        await source.daily_bars("AAPL", date(2026, 10, 1), date(2026, 10, 21))


async def test_auth_failure_makes_source_unhealthy(parts):
    source, _ = build(parts, [disconnect_bytes(807)])
    await source.start(["TCS"])
    await until(lambda: not source.healthy())
    await source.stop()


async def test_stop_closes_client_and_is_repeatable(parts):
    _, client, _ = parts
    source, _ = build(parts, [hang])
    await source.start(["TCS"])
    await source.stop()
    await source.stop()
    assert client.closed
    assert not source.healthy()


async def test_start_downloads_instruments_when_no_resolver(parts, monkeypatch):
    cache, client, resolver = parts
    downloads = []

    async def fake_download(http):
        downloads.append(http)
        return resolver

    monkeypatch.setattr(InstrumentResolver, "download", fake_download)
    source = DhanDataSource(cache, CREDENTIALS, client=client)
    source._feed = DhanFeed(CREDENTIALS, source._on_packet, connect=FakeConnect([hang]))
    await source.start(["TCS"])
    assert len(downloads) == 1
    await source.stop()
