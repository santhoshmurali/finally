"""Ticker <-> Dhan security ID resolution from the NSE instrument list."""

from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Segment-wise list: no auth, ~1.6 MB, 302-redirects to a pre-signed S3 URL.
NSE_EQ_URL = "https://api.dhan.co/v2/instrument/NSE_EQ"
REQUIRED_COLUMNS = {"EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "SERIES", "UNDERLYING_SYMBOL"}


@dataclass(frozen=True, slots=True)
class Instrument:
    ticker: str  # exchange symbol, e.g. "TCS"
    security_id: int
    segment: str  # "NSE_EQ"
    instrument: str  # "EQUITY"
    name: str = ""


class InstrumentResolver:
    def __init__(
        self,
        cache_dir: Path | str,
        max_age_s: float = 86_400,
        url: str = NSE_EQ_URL,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._path = Path(cache_dir) / "dhan-nse-eq-instruments.csv"
        self._max_age = max_age_s
        self._url = url
        self._http = http
        self._by_ticker: dict[str, Instrument] = {}
        self._by_key: dict[tuple[str, int], Instrument] = {}

    async def load(self) -> None:
        text = await self._read_or_download()
        self.load_text(text)

    def load_text(self, text: str) -> None:
        """Parse CSV text, keeping NSE EQUITY rows in series EQ."""
        reader = csv.DictReader(io.StringIO(text))
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(
                f"Dhan instrument list format changed; missing columns: {sorted(missing)}"
            )
        by_ticker: dict[str, Instrument] = {}
        by_key: dict[tuple[str, int], Instrument] = {}
        for row in reader:
            if not (
                row["EXCH_ID"] == "NSE"
                and row["SEGMENT"] == "E"
                and row["INSTRUMENT"] == "EQUITY"
                and row["SERIES"] == "EQ"
            ):
                continue
            inst = Instrument(
                row["UNDERLYING_SYMBOL"].strip().upper(),
                int(row["SECURITY_ID"]),
                "NSE_EQ",
                "EQUITY",
                (row.get("DISPLAY_NAME") or "").strip(),
            )
            by_ticker.setdefault(inst.ticker, inst)
            by_key[(inst.segment, inst.security_id)] = inst
        self._by_ticker = by_ticker
        self._by_key = by_key
        logger.info("Dhan instrument master loaded: %d NSE equities", len(by_ticker))

    def resolve(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker.strip().upper())

    def by_key(self, segment: str, security_id: int) -> Instrument | None:
        return self._by_key.get((segment, security_id))

    def __len__(self) -> int:
        return len(self._by_ticker)

    async def _read_or_download(self) -> str:
        fresh = self._path.exists() and time.time() - self._path.stat().st_mtime < self._max_age
        if fresh:
            return self._path.read_text()
        try:
            if self._http is not None:
                r = await self._http.get(self._url)
            else:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
                    r = await http.get(self._url)
            r.raise_for_status()
        except httpx.HTTPError:
            if self._path.exists():
                logger.warning("Dhan instrument download failed; using stale cached copy")
                return self._path.read_text()
            raise
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(r.text)
        except OSError:
            logger.warning("Could not cache Dhan instrument list at %s", self._path)
        return r.text
