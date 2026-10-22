"""Tests for DhanDataSource using a fake DhanClient (no network)."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.market.cache import PriceCache
from app.market.dhan.client import IST, DhanAuthError, DhanError, DhanRateLimited
from app.market.dhan.instruments import InstrumentResolver
from app.market.dhan.source import DhanDataSource, market_is_open
from app.market.models import Bar

CSV_TEXT = "\n".join(
    [
        "EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,SERIES,UNDERLYING_SYMBOL,DISPLAY_NAME",
        "NSE,E,11536,EQUITY,EQ,TCS,Tata Consultancy Services",
        "NSE,E,2885,EQUITY,EQ,RELIANCE,Reliance Industries",
        "NSE,E,1594,EQUITY,EQ,INFY,Infosys",
    ]
)
IDS = {"TCS": 11536, "RELIANCE": 2885, "INFY": 1594}


def today() -> date:
    return datetime.now(IST).date()


def bar(day: date, close: float) -> Bar:
    return Bar(day, close, close, close, close, 1000)


class FakeClient:
    """Stands in for DhanClient: configurable quotes/history, records calls."""

    def __init__(self):
        self.prices: dict[int, float] = {}
        self.ohlc_close: dict[int, float] = {}
        self.history: dict[int, list[Bar]] = {}
        self.ohlc_error: Exception | None = None
        self.history_error: Exception | None = None
        self.ohlc_calls: list[dict] = []
        self.history_calls: list[tuple] = []
        self.closed = False

    async def ohlc(self, securities):
        self.ohlc_calls.append({k: list(v) for k, v in securities.items()})
        if self.ohlc_error:
            raise self.ohlc_error
        out = {}
        for segment, ids in securities.items():
            for i in ids:
                if i in self.prices:
                    out.setdefault(segment, {})[i] = {
                        "last_price": self.prices[i],
                        "ohlc": {"close": self.ohlc_close.get(i, 0)},
                    }
        return out

    async def daily_bars(self, security_id, segment, start, end, instrument="EQUITY"):
        self.history_calls.append((security_id, segment, start, end))
        if self.history_error:
            raise self.history_error
        return [b for b in self.history.get(security_id, []) if start <= b.date <= end]

    async def aclose(self):
        self.closed = True


async def wait_until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.fixture
def cache():
    return PriceCache()


@pytest.fixture
def client():
    c = FakeClient()
    c.prices = {11536: 3900.0, 2885: 2900.0, 1594: 1500.0}
    c.history = {
        11536: [bar(today() - timedelta(days=3), 3850.0), bar(today(), 9999.0)],
        2885: [bar(today() - timedelta(days=2), 2880.0)],
    }
    return c


@pytest.fixture
def source(tmp_path, cache, client):
    (tmp_path / "dhan-nse-eq-instruments.csv").write_text(CSV_TEXT)
    return DhanDataSource(
        "cid",
        "tok",
        cache,
        cache_dir=tmp_path,
        poll_interval=1.0,
        client=client,
        resolver=InstrumentResolver(tmp_path),
    )


class TestMarketIsOpen:
    def test_open_during_session(self):
        assert market_is_open(datetime(2026, 10, 19, 10, 0, tzinfo=IST))  # Monday

    def test_boundaries(self):
        assert market_is_open(datetime(2026, 10, 19, 9, 15, tzinfo=IST))
        assert market_is_open(datetime(2026, 10, 19, 15, 30, tzinfo=IST))
        assert not market_is_open(datetime(2026, 10, 19, 9, 14, tzinfo=IST))
        assert not market_is_open(datetime(2026, 10, 19, 15, 31, tzinfo=IST))

    def test_weekend_closed(self):
        assert not market_is_open(datetime(2026, 10, 24, 11, 0, tzinfo=IST))  # Saturday

    def test_converts_timezone(self):
        # 05:00 UTC == 10:30 IST on a Monday
        assert market_is_open(datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc))
        # 03:00 UTC == 08:30 IST
        assert not market_is_open(datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc))

    def test_default_now_does_not_raise(self):
        assert isinstance(market_is_open(), bool)


class TestMetadata:
    def test_name_and_currency(self, source):
        assert source.name == "dhanhq"
        assert source.currency == "INR"

    def test_poll_interval_clamped_to_one_second(self, tmp_path, cache, client):
        s = DhanDataSource("c", "t", cache, tmp_path, poll_interval=0.1, client=client)
        assert s._interval == 1.0


class TestLifecycle:
    async def test_start_polls_and_writes_cache(self, source, cache, client):
        await source.start(["TCS", "RELIANCE"])
        try:
            await wait_until(lambda: "TCS" in cache and "RELIANCE" in cache)
        finally:
            await source.stop()

        assert cache.get_price("TCS") == 3900.0
        assert cache.get_price("RELIANCE") == 2900.0
        assert "INFY" not in cache
        assert sorted(source.get_tickers()) == ["RELIANCE", "TCS"]
        # One quote call covers every ticker in the segment
        assert client.ohlc_calls[0] == {"NSE_EQ": [11536, 2885]}

    async def test_previous_close_from_history_excludes_today(self, source, cache):
        await source.start(["TCS", "RELIANCE"])
        try:
            await wait_until(
                lambda: (u := cache.get("TCS")) is not None and u.previous_close is not None
            )
            await wait_until(
                lambda: (u := cache.get("RELIANCE")) is not None and u.previous_close is not None
            )
        finally:
            await source.stop()

        # today's partial bar (9999) must be ignored
        assert cache.get("TCS").previous_close == 3850.0
        assert cache.get("RELIANCE").previous_close == 2880.0
        assert cache.get("TCS").day_change_percent == pytest.approx(1.3, abs=0.01)

    async def test_previous_close_falls_back_to_ohlc_close_when_history_fails(
        self, source, cache, client
    ):
        client.history_error = DhanError("history down")
        client.ohlc_close = {11536: 3880.0}
        await source.start(["TCS"])
        try:
            await wait_until(
                lambda: (u := cache.get("TCS")) is not None and u.previous_close == 3880.0
            )
        finally:
            await source.stop()

    async def test_previous_close_none_when_history_empty_and_no_ohlc_close(
        self, source, cache, client
    ):
        client.history = {}
        await source.start(["INFY"])
        try:
            await wait_until(lambda: "INFY" in cache)
            await asyncio.sleep(0.05)
        finally:
            await source.stop()
        assert cache.get("INFY").previous_close is None
        assert cache.get("INFY").day_change_percent is None

    async def test_never_writes_zero_or_missing_prices(self, source, cache, client):
        client.prices = {11536: 0.0}  # zero for TCS, nothing for RELIANCE
        await source.start(["TCS", "RELIANCE"])
        try:
            await wait_until(lambda: len(client.ohlc_calls) >= 1)
            await asyncio.sleep(0.05)
        finally:
            await source.stop()
        assert len(cache) == 0

    async def test_unknown_tickers_are_skipped(self, source):
        await source.start(["TCS", "AAPL"])
        await source.stop()
        assert source.get_tickers() == ["TCS"]

    async def test_stop_closes_client_and_is_safe_twice(self, source, client):
        await source.start(["TCS"])
        await source.stop()
        assert client.closed
        await source.stop()

    async def test_add_ticker_polls_immediately(self, source, cache, client):
        client.prices = {}  # nothing available during start
        await source.start(["TCS"])
        try:
            await asyncio.sleep(0.05)
            client.prices = {2885: 2901.5}
            await source.add_ticker("reliance")
            await wait_until(lambda: "RELIANCE" in cache)
        finally:
            await source.stop()
        assert cache.get_price("RELIANCE") == 2901.5

    async def test_add_unknown_ticker_is_noop(self, source):
        await source.start([])
        await source.add_ticker("AAPL")
        await source.stop()
        assert source.get_tickers() == []

    async def test_add_duplicate_is_noop(self, source, client):
        await source.start(["TCS"])
        try:
            await wait_until(lambda: len(client.history_calls) >= 1)
            before = len(client.history_calls)
            await source.add_ticker("TCS")
            await asyncio.sleep(0.05)
        finally:
            await source.stop()
        assert len(client.history_calls) == before
        assert source.get_tickers() == ["TCS"]

    async def test_remove_ticker_clears_cache(self, source, cache):
        await source.start(["TCS", "RELIANCE"])
        try:
            await wait_until(lambda: "TCS" in cache)
            await source.remove_ticker("tcs")
        finally:
            await source.stop()
        assert "TCS" not in cache
        assert source.get_tickers() == ["RELIANCE"]

    async def test_remove_unknown_is_noop(self, source):
        await source.start(["TCS"])
        await source.remove_ticker("NOPE")
        await source.stop()
        assert source.get_tickers() == ["TCS"]


class TestRunLoopPolicy:
    """Drive _run_loop directly with a recording sleep to check backoff policy."""

    @staticmethod
    async def run_loop(source, monkeypatch, iterations):
        real_sleep = asyncio.sleep
        delays: list[float] = []

        async def fake_sleep(delay):
            delays.append(delay)
            if len(delays) >= iterations:
                raise asyncio.CancelledError
            await real_sleep(0)

        monkeypatch.setattr("app.market.dhan.source.asyncio.sleep", fake_sleep)
        with pytest.raises(asyncio.CancelledError):
            await source._run_loop()
        return delays

    async def test_rate_limit_doubles_delay_up_to_cap(self, source, client, monkeypatch):
        client.ohlc_error = DhanRateLimited("slow down")
        source._track("TCS")
        delays = await self.run_loop(source, monkeypatch, 7)
        assert delays == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
        assert source.healthy  # rate limiting is not an auth problem

    async def test_auth_error_marks_unhealthy_and_slows_polling(
        self, source, client, monkeypatch
    ):
        client.ohlc_error = DhanAuthError("expired", status=401, code="DH-901")
        source._track("TCS")
        delays = await self.run_loop(source, monkeypatch, 3)
        assert delays == [60.0, 60.0, 60.0]
        assert source.healthy is False

    async def test_recovers_after_auth_error(self, source, client, cache):
        client.ohlc_error = DhanAuthError("expired")
        source._track("TCS")
        with pytest.raises(DhanAuthError):
            await source._poll_once()
        client.ohlc_error = None
        await source._poll_once()
        assert source.healthy is True
        assert cache.get_price("TCS") == 3900.0

    async def test_unexpected_error_backs_off(self, source, client, monkeypatch):
        client.ohlc_error = DhanError("boom")
        source._track("TCS")
        delays = await self.run_loop(source, monkeypatch, 3)
        assert delays == [2.0, 4.0, 8.0]

    async def test_stale_prices_remain_in_cache_on_error(self, source, client, cache):
        source._track("TCS")
        await source._poll_once()
        client.ohlc_error = DhanError("down")
        with pytest.raises(DhanError):
            await source._poll_once()
        assert cache.get_price("TCS") == 3900.0

    async def test_open_market_uses_configured_interval(self, source, monkeypatch):
        monkeypatch.setattr("app.market.dhan.source.market_is_open", lambda *a: True)
        source._track("TCS")
        delays = await self.run_loop(source, monkeypatch, 2)
        assert delays == [1.0, 1.0]

    async def test_closed_market_polls_slowly(self, source, monkeypatch):
        monkeypatch.setattr("app.market.dhan.source.market_is_open", lambda *a: False)
        source._track("TCS")
        delays = await self.run_loop(source, monkeypatch, 2)
        assert delays == [30.0, 30.0]

    async def test_day_rollover_refreshes_previous_close(self, source, client, monkeypatch):
        monkeypatch.setattr("app.market.dhan.source.market_is_open", lambda *a: True)
        source._track("TCS")
        source._prev_close_day = today() - timedelta(days=1)
        await self.run_loop(source, monkeypatch, 2)
        assert source._prev_close_day == today()
        assert source._prev_close["TCS"] == 3850.0

    async def test_empty_watchlist_makes_no_calls(self, source, client, monkeypatch):
        await self.run_loop(source, monkeypatch, 2)
        assert client.ohlc_calls == []


class TestOnDemand:
    async def test_is_supported(self, source):
        await source._resolver.load()
        assert await source.is_supported("TCS")
        assert await source.is_supported("tcs")
        assert not await source.is_supported("AAPL")

    async def test_get_quotes(self, source, client):
        await source._resolver.load()
        quotes = await source.get_quotes(["TCS", "aapl", "RELIANCE"])
        assert set(quotes) == {"TCS", "RELIANCE"}
        assert quotes["TCS"].price == 3900.0
        assert quotes["TCS"].direction == "flat"

    async def test_get_quotes_uses_ohlc_close_as_previous_close(self, source, client):
        await source._resolver.load()
        client.ohlc_close = {11536: 3880.0}
        quotes = await source.get_quotes(["TCS"])
        assert quotes["TCS"].previous_close == 3880.0

    async def test_get_quotes_omits_missing_and_zero(self, source, client):
        await source._resolver.load()
        client.prices = {11536: 0.0}
        assert await source.get_quotes(["TCS", "RELIANCE"]) == {}

    async def test_get_quotes_all_unknown_makes_no_call(self, source, client):
        await source._resolver.load()
        assert await source.get_quotes(["AAPL"]) == {}
        assert client.ohlc_calls == []

    async def test_get_quotes_does_not_touch_cache(self, source, cache):
        await source._resolver.load()
        await source.get_quotes(["TCS"])
        assert len(cache) == 0

    async def test_get_daily_bars(self, source, client):
        await source._resolver.load()
        t = today()
        bars = await source.get_daily_bars("TCS", t - timedelta(days=5), t)
        assert [b.close for b in bars] == [3850.0, 9999.0]
        assert client.history_calls[0][:2] == (11536, "NSE_EQ")

    async def test_get_daily_bars_unknown_ticker(self, source):
        await source._resolver.load()
        assert await source.get_daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 2)) == []

    async def test_get_eod_closes_on_date(self, source, client):
        await source._resolver.load()
        d = today() - timedelta(days=2)
        client.history = {
            11536: [bar(d - timedelta(days=1), 100.0), bar(d, 101.0)],
            2885: [bar(d, 202.0)],
        }
        closes = await source.get_eod_closes(["TCS", "RELIANCE", "INFY", "AAPL"], on=d)
        assert closes == {"TCS": 101.0, "RELIANCE": 202.0}

    async def test_get_eod_closes_default_day(self, source, client):
        await source._resolver.load()
        closes = await source.get_eod_closes(["RELIANCE"])
        assert closes == {"RELIANCE": 2880.0}

    async def test_get_eod_closes_skips_failed_tickers(self, source, client):
        await source._resolver.load()
        client.history_error = DhanError("down")
        assert await source.get_eod_closes(["TCS"], on=today()) == {}
