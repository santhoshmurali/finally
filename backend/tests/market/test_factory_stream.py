"""Source selection from the environment, and the SSE price stream."""

import base64
import json
import time

import pytest

from app.market import (
    AuthenticationError,
    MarketDataSource,
    PriceCache,
    create_market_source,
)
from app.market.dhan.source import DhanDataSource
from app.market.simulator import SimulatorDataSource
from app.market.stream import RETRY_MILLISECONDS, create_stream_router, price_events


def make_token(exp):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'x'})}.{part({'exp': exp, 'dhanClientId': '1100'})}.sig"


def test_no_token_gives_simulator():
    source = create_market_source(PriceCache(), {})
    assert isinstance(source, SimulatorDataSource)


def test_blank_token_gives_simulator():
    assert isinstance(create_market_source(PriceCache(), {"DHAN_ACESS_TOKEN": "  "}),
                      SimulatorDataSource)


def test_token_gives_dhan_source_and_every_source_is_a_market_data_source():
    env = {"DHAN_ACESS_TOKEN": f'"{make_token(time.time() + 3600)}"'}
    source = create_market_source(PriceCache(), env)
    assert isinstance(source, DhanDataSource)
    assert isinstance(source, MarketDataSource)
    assert isinstance(create_market_source(PriceCache(), {}), MarketDataSource)


def test_expired_token_raises():
    with pytest.raises(AuthenticationError):
        create_market_source(PriceCache(), {"DHAN_ACCESS_TOKEN": make_token(time.time() - 5)})


def test_market_seed_is_used():
    source = create_market_source(PriceCache(), {"MARKET_SEED": "42"})
    assert source._seed == 42


def test_reads_process_environment_by_default(monkeypatch):
    monkeypatch.delenv("DHAN_ACESS_TOKEN", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    assert isinstance(create_market_source(PriceCache()), SimulatorDataSource)


class FakeRequest:
    """Reports disconnected after `connected_checks` calls."""

    def __init__(self, connected_checks):
        self.remaining = connected_checks

    async def is_disconnected(self):
        self.remaining -= 1
        return self.remaining < 0


async def collect(cache, checks, interval=0.001):
    return [event async for event in price_events(cache, FakeRequest(checks), interval)]


async def test_stream_starts_with_retry_hint_and_sends_all_prices():
    cache = PriceCache()
    cache.update("TCS", 100.0, previous_close=90.0)
    cache.update("INFY", 50.0)
    events = await collect(cache, 1)
    assert events[0] == f"retry: {RETRY_MILLISECONDS}\n\n"
    payload = json.loads(events[1].removeprefix("data: "))
    assert set(payload) == {"TCS", "INFY"}
    assert payload["TCS"]["day_change_percent"] == pytest.approx(11.1111, abs=0.001)
    assert events[1].endswith("\n\n")


async def test_stream_only_sends_when_cache_changed():
    cache = PriceCache()
    cache.update("TCS", 100.0)
    events = await collect(cache, 4)
    assert len(events) == 2  # retry hint + one data event despite four polls


async def test_stream_sends_again_after_update():
    cache = PriceCache()
    cache.update("TCS", 100.0)
    events = []
    request = FakeRequest(6)
    async for event in price_events(cache, request, 0.001):
        events.append(event)
        if len(events) == 2:
            cache.update("TCS", 101.0)
    assert len(events) == 3
    assert json.loads(events[2].removeprefix("data: "))["TCS"]["direction"] == "up"


async def test_stream_with_empty_cache_sends_empty_object():
    events = await collect(PriceCache(), 1)
    assert events[1] == "data: {}\n\n"


def test_router_registers_price_stream_route():
    router = create_stream_router(PriceCache())
    assert [r.path for r in router.routes] == ["/api/stream/prices"]


async def test_endpoint_returns_event_stream_response():
    cache = PriceCache()
    cache.update("TCS", 100.0)
    endpoint = create_stream_router(cache, interval=0.001).routes[0].endpoint
    response = await endpoint(FakeRequest(1))
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks[0] == f"retry: {RETRY_MILLISECONDS}\n\n"
    assert "TCS" in chunks[1]
