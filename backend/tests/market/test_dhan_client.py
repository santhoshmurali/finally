"""DhanClient history parsing and error mapping against a mock transport."""

import asyncio
import json
from datetime import date

import httpx
import pytest

from app.market.dhan import client as client_module
from app.market.dhan.auth import Credentials
from app.market.dhan.client import DhanClient
from app.market.errors import (
    AuthenticationError,
    DataUnavailableError,
    RateLimitError,
)

CREDENTIALS = Credentials("secret-token", "1100", 9e12)

# 2026-10-20 and 2026-10-21 stamped at IST midnight.
HISTORY = {
    "open": [10, 20], "high": [11, 21], "low": [9, 19], "close": [10.5, 20.5],
    "volume": [100, 200], "timestamp": [1792434600, 1792521000], "open_interest": [0, 0],
}


def make_client(handler) -> DhanClient:
    http = httpx.AsyncClient(base_url="https://x/v2", transport=httpx.MockTransport(handler))
    return DhanClient(CREDENTIALS, http)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(client_module, "MIN_REQUEST_GAP", 0)


async def test_daily_bars_parse_and_filter_by_ist_date():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=HISTORY)

    bars = await make_client(handler).daily_bars(11536, date(2026, 10, 21), date(2026, 10, 21))
    assert [(b.day, b.close, b.volume) for b in bars] == [(date(2026, 10, 21), 20.5, 200)]
    assert seen["headers"]["access-token"] == "secret-token"
    assert seen["headers"]["client-id"] == "1100"
    assert seen["body"]["securityId"] == "11536"
    assert seen["body"]["toDate"] == "2026-10-22"  # non-inclusive, so end + 1 day


async def test_no_data_error_gives_empty_list():
    body = {"errorType": "Data_Error", "errorCode": "DH-907", "errorMessage": "no data"}
    client = make_client(lambda request: httpx.Response(400, json=body))
    assert await client.daily_bars(1, date(2026, 10, 24), date(2026, 10, 25)) == []


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"errorCode": "DH-901", "errorMessage": "bad token"}, AuthenticationError),
        (401, {"data": {"808": "Authentication Failed"}, "status": "failed"}, AuthenticationError),
        (400, {"errorCode": "DH-902", "errorMessage": "no data plan"}, AuthenticationError),
        (429, {"errorCode": "DH-904", "errorMessage": "slow down"}, RateLimitError),
        (400, {"data": {"805": "Too many requests"}, "status": "failed"}, RateLimitError),
        (500, {"errorCode": "DH-908", "errorMessage": "server"}, DataUnavailableError),
        (502, "not json", DataUnavailableError),
    ],
)
async def test_error_mapping(status, body, expected):
    def handler(request):
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    with pytest.raises(expected):
        await make_client(handler).daily_bars(1, date(2026, 10, 1), date(2026, 10, 2))


async def test_network_error_is_data_unavailable():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(DataUnavailableError):
        await make_client(handler).daily_bars(1, date(2026, 10, 1), date(2026, 10, 2))


async def test_requests_are_spaced(monkeypatch):
    monkeypatch.setattr(client_module, "MIN_REQUEST_GAP", 0.05)
    client = make_client(lambda request: httpx.Response(200, json=HISTORY))
    start = asyncio.get_running_loop().time()
    for _ in range(3):
        await client.daily_bars(1, date(2026, 10, 1), date(2026, 10, 30))
    assert asyncio.get_running_loop().time() - start >= 0.09


async def test_unrecognised_error_body_is_data_unavailable():
    client = make_client(lambda request: httpx.Response(400, json={"surprise": True}))
    with pytest.raises(DataUnavailableError, match="surprise"):
        await client.daily_bars(1, date(2026, 10, 1), date(2026, 10, 2))


async def test_close_closes_the_http_client():
    client = make_client(lambda request: httpx.Response(200, json=HISTORY))
    await client.close()
    assert client._http.is_closed


@pytest.mark.parametrize(
    "reply",
    [{"unexpected": 1}, {"timestamp": [1792521000], "open": []}, "<html>gateway</html>"],
)
async def test_malformed_success_reply_is_data_unavailable(reply):
    def handler(request):
        if isinstance(reply, str):
            return httpx.Response(200, text=reply)
        return httpx.Response(200, json=reply)

    with pytest.raises(DataUnavailableError):
        await make_client(handler).daily_bars(1, date(2026, 10, 1), date(2026, 10, 30))
