"""Ticker <-> Dhan security ID mapping from the public NSE equity instrument list."""

from __future__ import annotations

import csv
import io

import httpx

from ..errors import DataUnavailableError, UnsupportedTickerError

NSE_EQUITY_URL = "https://api.dhan.co/v2/instrument/NSE_EQ"
SEGMENT = "NSE_EQ"


class InstrumentResolver:
    """Resolves NSE cash-equity tickers (series EQ) to security IDs and back."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._tickers: dict[int, str] = {}

    @classmethod
    def from_csv(cls, text: str) -> InstrumentResolver:
        """Build from the segment-wise instrument CSV (no auth needed to download)."""
        resolver = cls()
        for row in csv.DictReader(io.StringIO(text)):
            if row["INSTRUMENT"] == "EQUITY" and row["SERIES"] == "EQ":
                resolver._add(row["UNDERLYING_SYMBOL"].strip().upper(), int(row["SECURITY_ID"]))
        return resolver

    @classmethod
    async def download(cls, http: httpx.AsyncClient) -> InstrumentResolver:
        """Fetch the list. Dhan answers with a redirect to a pre-signed S3 URL."""
        try:
            response = await http.get(NSE_EQUITY_URL, follow_redirects=True, timeout=60)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DataUnavailableError(f"Dhan instrument list download failed: {exc}") from exc
        return cls.from_csv(response.text)

    def _add(self, ticker: str, security_id: int) -> None:
        self._ids[ticker] = security_id
        self._tickers[security_id] = ticker

    def security_id(self, ticker: str) -> int:
        """Security ID of `ticker`; raises `UnsupportedTickerError` if not an NSE EQ stock."""
        try:
            return self._ids[ticker.upper()]
        except KeyError:
            raise UnsupportedTickerError(f"{ticker} is not an NSE equity") from None

    def ticker(self, security_id: int) -> str | None:
        return self._tickers.get(security_id)

    def __contains__(self, ticker: str) -> bool:
        return ticker.upper() in self._ids

    def __len__(self) -> int:
        return len(self._ids)
