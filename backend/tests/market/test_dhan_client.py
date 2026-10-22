"""Tests for the async Dhan REST client (offline, via httpx.MockTransport)."""

import json
import time
from datetime import date, datetime

import httpx
import pytest

from app.market.dhan.client import (
    IST,
    DhanAuthError,
    DhanClient,
    DhanError,
    DhanRateLimited,
    Throttle,
    parse_error,
)

BASE = "https://api.dhan.co/v2"


def make_client(handler) -> DhanClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=BASE,
        headers={"access-token": "tok", "client-id": "cid"},
    )
    return DhanClient("cid", "tok", http=http, quote_interval=0, data_interval=0)


def ts(day: date) -> int:
    """Epoch seconds for IST midnight of ``day`` (how Dhan stamps daily candles)."""
    return int(datetime(day.year, day.month, day.day, tzinfo=IST).timestamp())


class TestOhlc:
    async def test_request_shape_and_parsing(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            seen["headers"] = request.headers
            return httpx.Response(
                200,
                json={
                    "data": {
                        "NSE_EQ": {
                            "11536": {"last_price": 4525.55, "ohlc": {"close": 4507.85}},
                            "2885": {"last_price": 2900.0, "ohlc": {"close": 2890.0}},
                        }
                    },
                    "status": "success",
                },
            )

        client = make_client(handler)
        out = await client.ohlc({"NSE_EQ": [11536, 2885]})

        assert seen["path"] == "/v2/marketfeed/ohlc"
        assert seen["body"] == {"NSE_EQ": [11536, 2885]}
        assert seen["headers"]["access-token"] == "tok"
        assert seen["headers"]["client-id"] == "cid"
        # String keys in the response become ints
        assert out["NSE_EQ"][11536]["last_price"] == 4525.55
        assert out["NSE_EQ"][2885]["ohlc"]["close"] == 2890.0

    async def test_chunks_at_1000_ids(self):
        sizes = []

        def handler(request: httpx.Request) -> httpx.Response:
            ids = json.loads(request.content)["NSE_EQ"]
            sizes.append(len(ids))
            return httpx.Response(
                200,
                json={"data": {"NSE_EQ": {str(i): {"last_price": 1.0} for i in ids}}},
            )

        client = make_client(handler)
        out = await client.ohlc({"NSE_EQ": list(range(2500))})

        assert sizes == [1000, 1000, 500]
        assert len(out["NSE_EQ"]) == 2500

    async def test_missing_segment_in_response_is_empty(self):
        client = make_client(lambda r: httpx.Response(200, json={"data": {}, "status": "success"}))
        assert await client.ohlc({"NSE_EQ": [1]}) == {}


class TestDailyBars:
    async def test_request_shape(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"open": [], "high": [], "low": [], "close": [], "volume": [], "timestamp": []},
            )

        client = make_client(handler)
        await client.daily_bars(11536, "NSE_EQ", date(2026, 10, 1), date(2026, 10, 10))

        assert seen["path"] == "/v2/charts/historical"
        assert seen["body"] == {
            "securityId": "11536",  # string, not int
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": "2026-10-01",
            "toDate": "2026-10-11",  # non-inclusive, so end + 1 day
        }

    async def test_parses_columns_and_filters_range(self):
        days = [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]
        body = {
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [100.0, 200.0, 300.0],
            "timestamp": [ts(d) for d in days],
        }
        client = make_client(lambda r: httpx.Response(200, json=body))

        bars = await client.daily_bars(1, "NSE_EQ", date(2026, 10, 6), date(2026, 10, 7))

        assert [b.date for b in bars] == days[1:]
        assert bars[0].close == 11.5
        assert bars[0].volume == 200
        assert isinstance(bars[0].volume, int)

    async def test_no_data_returns_empty(self):
        client = make_client(
            lambda r: httpx.Response(
                400, json={"errorType": "Data_Error", "errorCode": "DH-907", "errorMessage": "x"}
            )
        )
        assert await client.daily_bars(1, "NSE_EQ", date(2026, 1, 1), date(2026, 1, 2)) == []


class TestErrorMapping:
    @pytest.mark.parametrize(
        "status,body",
        [
            (401, {"errorType": "Invalid_Authentication", "errorCode": "DH-901", "errorMessage": "bad"}),
            (401, {"data": {"808": "Authentication Failed"}, "status": "failed"}),
            (400, {"errorCode": "DH-902", "errorMessage": "no data plan"}),
            (400, {"data": {"806": "Data APIs not subscribed"}, "status": "failed"}),
            (403, {}),
        ],
    )
    async def test_auth_errors(self, status, body):
        client = make_client(lambda r: httpx.Response(status, json=body))
        with pytest.raises(DhanAuthError):
            await client.ohlc({"NSE_EQ": [1]})

    @pytest.mark.parametrize(
        "status,body",
        [
            (429, {}),
            (400, {"errorCode": "DH-904", "errorMessage": "rate"}),
            (400, {"data": {"805": "Too many requests"}, "status": "failed"}),
        ],
    )
    async def test_rate_limit_errors(self, status, body):
        client = make_client(lambda r: httpx.Response(status, json=body))
        with pytest.raises(DhanRateLimited):
            await client.ohlc({"NSE_EQ": [1]})

    async def test_other_error_keeps_code_and_status(self):
        client = make_client(
            lambda r: httpx.Response(
                400, json={"errorCode": "DH-905", "errorMessage": "securityId is required"}
            )
        )
        with pytest.raises(DhanError) as exc:
            await client.ohlc({"NSE_EQ": [1]})
        assert not isinstance(exc.value, (DhanAuthError, DhanRateLimited))
        assert exc.value.code == "DH-905"
        assert exc.value.status == 400
        assert "securityId is required" in str(exc.value)

    async def test_network_error_wrapped(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        client = make_client(handler)
        with pytest.raises(DhanError):
            await client.ohlc({"NSE_EQ": [1]})

    async def test_invalid_json_success_body(self):
        client = make_client(lambda r: httpx.Response(200, text="<html>"))
        with pytest.raises(DhanError):
            await client.ohlc({"NSE_EQ": [1]})


class TestParseError:
    def test_non_json_body(self):
        code, msg = parse_error(httpx.Response(502, text="Bad Gateway"))
        assert code is None
        assert msg == "Bad Gateway"

    def test_trading_style(self):
        code, msg = parse_error(
            httpx.Response(400, json={"errorCode": "DH-905", "errorMessage": "m"})
        )
        assert (code, msg) == ("DH-905", "m")

    def test_quote_style(self):
        code, msg = parse_error(
            httpx.Response(401, json={"data": {"808": "auth"}, "status": "failed"})
        )
        assert (code, msg) == ("808", "auth")

    def test_unrecognised_json(self):
        code, _ = parse_error(httpx.Response(500, json={"foo": "bar"}))
        assert code is None


class TestThrottle:
    async def test_spaces_calls(self):
        gate = Throttle(0.05)
        start = time.monotonic()
        await gate.wait()
        await gate.wait()
        await gate.wait()
        assert time.monotonic() - start >= 0.09

    async def test_zero_interval_does_not_delay(self):
        gate = Throttle(0)
        start = time.monotonic()
        for _ in range(5):
            await gate.wait()
        assert time.monotonic() - start < 0.05


async def test_aclose():
    client = make_client(lambda r: httpx.Response(200, json={}))
    await client.aclose()
    assert client._http.is_closed
