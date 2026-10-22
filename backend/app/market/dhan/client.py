"""Async REST client for the DhanHQ v2 market quote and historical APIs."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from ..interface import MarketDataError
from ..models import Bar

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Error codes from the official Annexure (planning/DHANHQ_API.md §10)
_AUTH_CODES = {"DH-901", "DH-902", "806", "807", "808", "809", "810"}
_RATE_CODES = {"DH-904", "805"}

QUOTE_BATCH = 1000  # max instruments per quote request


class DhanError(MarketDataError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class DhanAuthError(DhanError):
    """Bad/expired token, bad client id, or no Data API subscription (not retryable)."""


class DhanRateLimited(DhanError):
    """429 / DH-904 / 805: retry after backoff."""


class DhanNoData(DhanError):
    """DH-907: no data for the request."""


def parse_error(response: httpx.Response) -> tuple[str | None, str]:
    """Extract (code, message) from either of Dhan's two error body shapes.

    trading/charts: {"errorType", "errorCode": "DH-901", "errorMessage"}
    quote:          {"data": {"808": "message"}, "status": "failed"}
    """
    try:
        body = response.json()
    except ValueError:
        return None, response.text[:200]
    if isinstance(body, dict):
        if body.get("errorCode"):
            return str(body["errorCode"]), str(body.get("errorMessage", ""))
        data = body.get("data")
        if body.get("status") == "failed" and isinstance(data, dict) and data:
            code, msg = next(iter(data.items()))
            return str(code), str(msg)
    return None, response.text[:200]


class Throttle:
    """Allow at most one call per ``min_interval`` seconds across concurrent tasks."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = max(now, self._next) + self._min


class DhanClient:
    BASE_URL = "https://api.dhan.co/v2"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        *,
        base_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        quote_interval: float = 1.05,
        data_interval: float = 0.25,
    ) -> None:
        self._http = http or httpx.AsyncClient(
            base_url=base_url or self.BASE_URL,
            headers={
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(10.0),
        )
        self._quote_gate = Throttle(quote_interval)  # Quote APIs: 1 req/s
        self._data_gate = Throttle(data_interval)  # Data APIs: 5 req/s

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict, gate: Throttle) -> dict:
        await gate.wait()
        try:
            r = await self._http.post(path, json=body)
        except httpx.HTTPError as e:
            raise DhanError(f"{path}: {e.__class__.__name__}: {e}") from e
        if r.status_code >= 400:
            code, msg = parse_error(r)
            detail = f"{path}: HTTP {r.status_code} {code or ''} {msg}".strip()
            if r.status_code == 429 or code in _RATE_CODES:
                raise DhanRateLimited(detail, status=r.status_code, code=code)
            if r.status_code in (401, 403) or code in _AUTH_CODES:
                raise DhanAuthError(detail, status=r.status_code, code=code)
            if code == "DH-907":
                raise DhanNoData(detail, status=r.status_code, code=code)
            raise DhanError(detail, status=r.status_code, code=code)
        try:
            return r.json()
        except ValueError as e:
            raise DhanError(f"{path}: invalid JSON in response") from e

    async def ohlc(self, securities: dict[str, list[int]]) -> dict[str, dict[int, dict]]:
        """{segment: [ids]} -> {segment: {security_id: {last_price, ohlc{...}}}}.

        Splits into chunks of at most 1000 ids per request (API limit).
        """
        out: dict[str, dict[int, dict]] = {}
        for segment, ids in securities.items():
            for i in range(0, len(ids), QUOTE_BATCH):
                chunk = ids[i : i + QUOTE_BATCH]
                body = await self._post("/marketfeed/ohlc", {segment: chunk}, self._quote_gate)
                data = body.get("data") or {}
                for sec_id, q in (data.get(segment) or {}).items():
                    out.setdefault(segment, {})[int(sec_id)] = q
        return out

    async def daily_bars(
        self,
        security_id: int,
        segment: str,
        start: date,
        end: date,
        instrument: str = "EQUITY",
    ) -> list[Bar]:
        """Daily candles with ``start <= IST trading date <= end``, ascending."""
        try:
            body = await self._post(
                "/charts/historical",
                {
                    "securityId": str(security_id),
                    "exchangeSegment": segment,
                    "instrument": instrument,
                    "expiryCode": 0,
                    "oi": False,
                    "fromDate": start.isoformat(),
                    "toDate": (end + timedelta(days=1)).isoformat(),  # non-inclusive
                },
                self._data_gate,
            )
        except DhanNoData:
            return []
        bars: list[Bar] = []
        for i, ts in enumerate(body.get("timestamp") or []):
            day = datetime.fromtimestamp(ts, IST).date()
            if start <= day <= end:
                bars.append(
                    Bar(
                        day,
                        body["open"][i],
                        body["high"][i],
                        body["low"][i],
                        body["close"][i],
                        int(body["volume"][i]),
                    )
                )
        return bars
