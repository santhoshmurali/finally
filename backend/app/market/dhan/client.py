"""Async REST client for the Dhan endpoints FinAlly needs (daily history)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta, timezone

import httpx

from ..errors import (
    AuthenticationError,
    DataUnavailableError,
    MarketDataError,
    RateLimitError,
)
from ..models import Bar
from .auth import Credentials
from .instruments import SEGMENT

BASE_URL = "https://api.dhan.co/v2"
IST = timezone(timedelta(hours=5, minutes=30))
MIN_REQUEST_GAP = 0.2  # Data APIs allow 5 requests per second

AUTH_CODES = {"DH-901", "DH-902", "806", "807", "808", "809", "810"}
RATE_LIMIT_CODES = {"DH-904", "805"}
NO_DATA_CODE = "DH-907"


class NoDataError(MarketDataError):
    """Dhan has no data for the request (for example an empty date range)."""


class DhanClient:
    """Thin wrapper over `httpx.AsyncClient`; maps Dhan errors to `MarketDataError`s."""

    def __init__(self, credentials: Credentials, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(base_url=BASE_URL, timeout=15)
        self._headers = {
            "access-token": credentials.token,
            "client-id": credentials.client_id,
            "Content-Type": "application/json",
        }
        self._gap_lock = asyncio.Lock()
        self._last_request = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def daily_bars(self, security_id: int, start: date, end: date) -> list[Bar]:
        """Completed daily candles with `start <= day <= end`; empty if Dhan has none."""
        body = {
            "securityId": str(security_id),
            "exchangeSegment": SEGMENT,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": start.isoformat(),
            "toDate": (end + timedelta(days=1)).isoformat(),  # toDate is non-inclusive
        }
        try:
            data = await self._post("/charts/historical", body)
        except NoDataError:
            return []
        try:
            return _bars_from_columns(data, start, end)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DataUnavailableError(f"Unexpected Dhan history reply: {exc!r}") from exc

    async def _post(self, path: str, body: dict) -> dict:
        await self._throttle()
        try:
            response = await self._http.post(path, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise DataUnavailableError(f"Dhan request failed: {exc}") from exc
        if not response.is_success:
            raise _error_from(response)
        try:
            return response.json()
        except ValueError as exc:
            raise DataUnavailableError("Dhan returned a non-JSON reply") from exc

    async def _throttle(self) -> None:
        async with self._gap_lock:
            wait = self._last_request + MIN_REQUEST_GAP - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


def _bars_from_columns(data: dict, start: date, end: date) -> list[Bar]:
    """Dhan returns parallel arrays; daily candles are stamped at IST midnight."""
    bars = []
    for i, stamp in enumerate(data["timestamp"]):
        day = datetime.fromtimestamp(stamp, UTC).astimezone(IST).date()
        if start <= day <= end:
            bars.append(Bar(day, data["open"][i], data["high"][i], data["low"][i],
                            data["close"][i], int(data["volume"][i])))
    return bars


def _error_code(response: httpx.Response) -> tuple[str, str]:
    """Extract (code, message) from either Dhan error body shape."""
    try:
        body = response.json()
    except ValueError:
        return "", response.text[:200]
    if "errorCode" in body:
        return str(body["errorCode"]), str(body.get("errorMessage", ""))
    if isinstance(body.get("data"), dict) and body["data"]:
        code, message = next(iter(body["data"].items()))
        return str(code), str(message)
    return "", str(body)[:200]


def _error_from(response: httpx.Response) -> MarketDataError:
    code, message = _error_code(response)
    text = f"Dhan error {code or response.status_code}: {message}"
    if code in AUTH_CODES or response.status_code in (401, 403):
        return AuthenticationError(text)
    if code in RATE_LIMIT_CODES or response.status_code == 429:
        return RateLimitError(text)
    if code == NO_DATA_CODE:
        return NoDataError(text)
    return DataUnavailableError(text)
