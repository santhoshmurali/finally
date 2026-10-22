"""DhanFeed: subscribe, dispatch, reconnect, backoff and fatal-auth handling."""

import asyncio
import time

import pytest
from websockets.exceptions import ConnectionClosedError

from app.market.dhan import feed as feed_module
from app.market.dhan.auth import Credentials
from app.market.dhan.feed import DhanFeed
from app.market.dhan.packets import PreviousClose, Tick
from app.market.errors import AuthenticationError

from .dhan_fakes import FakeConnect, disconnect_bytes, prev_close_bytes, ticker_bytes

CREDENTIALS = Credentials("tok-123", "1100", time.time() + 3600)
DROPPED = ConnectionClosedError(None, None)


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff sleeps without waiting."""
    delays = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        if delay:
            delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(feed_module.asyncio, "sleep", fake_sleep)
    return delays


def make_feed(connect, packets=None, credentials=CREDENTIALS):
    sink = packets if packets is not None else []
    return DhanFeed(credentials, sink.append, connect=connect), sink


async def test_subscribes_on_connect_and_dispatches_packets():
    feed = None
    connect = FakeConnect([ticker_bytes(11536, 2506.9), prev_close_bytes(11536, 2529.0),
                           lambda: feed.stop()])
    feed, packets = make_feed(connect)
    await feed.subscribe([11536, 2885])
    await feed.run()
    assert packets == [Tick("NSE_EQ", 11536, 2506.9), PreviousClose("NSE_EQ", 11536, 2529.0)]
    message = connect.connections[0].sent[0]
    assert message["RequestCode"] == 15
    assert message["InstrumentCount"] == 2
    assert {i["SecurityId"] for i in message["InstrumentList"]} == {"11536", "2885"}
    assert message["InstrumentList"][0]["ExchangeSegment"] == "NSE_EQ"


async def test_connection_url_carries_credentials():
    feed = None
    connect = FakeConnect([lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.run()
    assert "token=tok-123" in connect.urls[0]
    assert "clientId=1100" in connect.urls[0]
    assert "authType=2" in connect.urls[0]


async def test_subscriptions_are_batched_by_100():
    feed = None
    connect = FakeConnect([lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.subscribe(list(range(1, 251)))
    await feed.run()
    assert [m["InstrumentCount"] for m in connect.connections[0].sent] == [100, 100, 50]


async def test_reconnects_and_resubscribes_after_drop(sleeps):
    feed = None
    connect = FakeConnect(
        [ticker_bytes(1, 10.0), DROPPED],
        [ticker_bytes(1, 11.0), lambda: feed.stop()],
    )
    feed, packets = make_feed(connect)
    await feed.subscribe([1])
    await feed.run()
    assert [p.price for p in packets] == [10.0, 11.0]
    assert len(connect.connections) == 2
    assert connect.connections[1].sent[0]["InstrumentList"][0]["SecurityId"] == "1"
    assert sleeps == [1.0]


async def test_backoff_doubles_and_caps_when_nothing_is_received(sleeps):
    feed = None
    connect = FakeConnect(DROPPED, OSError("down"), DROPPED, DROPPED, [lambda: feed.stop()])
    feed, _ = make_feed(connect)
    feed._max_backoff = 5.0
    await feed.run()
    assert sleeps == [2.0, 4.0, 5.0, 5.0]


async def test_unhealthy_after_repeated_failures_and_recovers(monkeypatch):
    feed = None
    health_at_backoff = []
    real_sleep = asyncio.sleep

    async def spy_sleep(delay):
        if delay:
            health_at_backoff.append(feed.healthy)
        await real_sleep(0)

    monkeypatch.setattr(feed_module.asyncio, "sleep", spy_sleep)
    connect = FakeConnect(DROPPED, DROPPED, DROPPED, [ticker_bytes(1, 5.0), DROPPED],
                          [lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.run()
    assert health_at_backoff == [True, True, False, True]
    assert feed.healthy


@pytest.mark.parametrize("code", [806, 807, 808, 809])
async def test_auth_disconnect_is_fatal(code, sleeps):
    connect = FakeConnect([disconnect_bytes(code)])
    feed, _ = make_feed(connect)
    await feed.run()
    assert isinstance(feed.error, AuthenticationError)
    assert not feed.healthy
    assert len(connect.connections) == 1
    assert sleeps == []


async def test_other_disconnect_reconnects(sleeps):
    feed = None
    connect = FakeConnect([disconnect_bytes(805)], [lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.run()
    assert feed.error is None
    assert len(connect.connections) == 2


async def test_expired_token_stops_without_connecting():
    expired = Credentials("t", "1", time.time() - 1)
    connect = FakeConnect()
    feed, _ = make_feed(connect, credentials=expired)
    await feed.run()
    assert isinstance(feed.error, AuthenticationError)
    assert connect.urls == []


async def test_subscribe_and_unsubscribe_while_connected():
    gate = asyncio.Event()
    feed = None

    async def wait_for_gate():
        await gate.wait()

    connect = FakeConnect([wait_for_gate, lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.subscribe([1])
    task = asyncio.create_task(feed.run())
    while not connect.connections:
        await asyncio.sleep(0)
    await feed.subscribe([1, 2])
    await feed.unsubscribe([2, 99])
    gate.set()
    await task
    sent = connect.connections[0].sent
    assert [(m["RequestCode"], m["InstrumentCount"]) for m in sent] == [(15, 1), (15, 1), (16, 1)]
    assert sent[1]["InstrumentList"][0]["SecurityId"] == "2"
    assert sent[2]["InstrumentList"][0]["SecurityId"] == "2"


async def test_unsubscribed_ids_are_not_resubscribed_on_reconnect(sleeps):
    feed = None
    connect = FakeConnect([DROPPED], [lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.subscribe([1, 2])
    await feed.unsubscribe([2])
    await feed.run()
    resent = connect.connections[1].sent[0]["InstrumentList"]
    assert [i["SecurityId"] for i in resent] == ["1"]


async def test_stop_closes_the_socket():
    feed = None
    connect = FakeConnect([lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.run()
    assert connect.connections[0].closed


async def test_repeated_server_disconnects_back_off_and_turn_unhealthy(sleeps):
    feed = None
    connect = FakeConnect([disconnect_bytes(805)], [disconnect_bytes(805)],
                          [disconnect_bytes(805)], [lambda: feed.stop()])
    feed, _ = make_feed(connect)
    await feed.run()
    assert sleeps == [2.0, 4.0, 8.0]
    assert not feed.healthy


async def test_undecodable_frames_are_skipped():
    feed = None
    connect = FakeConnect([b"", b"\x02\x10", ticker_bytes(1, 7.0), lambda: feed.stop()])
    feed, packets = make_feed(connect)
    await feed.run()
    assert [p.price for p in packets] == [7.0]


async def test_failing_callback_does_not_kill_the_feed():
    feed = None
    seen = []

    def flaky(packet):
        seen.append(packet.price)
        if packet.price == 1.0:
            raise RuntimeError("consumer bug")

    connect = FakeConnect([ticker_bytes(1, 1.0), ticker_bytes(1, 2.0), lambda: feed.stop()])
    feed = DhanFeed(CREDENTIALS, flaky, connect=connect)
    await feed.run()
    assert seen == [1.0, 2.0]


async def test_subscribe_on_a_dropped_socket_keeps_the_id_for_reconnect():
    class DeadSocket:
        async def send(self, message):
            raise DROPPED

    feed, _ = make_feed(FakeConnect())
    feed._ws = DeadSocket()
    await feed.subscribe([5])
    assert 5 in feed._security_ids
