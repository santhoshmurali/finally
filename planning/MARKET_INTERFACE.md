# Unified Market Data Interface

Design of the single Python API the FinAlly backend uses to get stock prices (real-time and end-of-day). It uses **DhanHQ** when `DHANHQ_API_KEY` is set, and the built-in **simulator** otherwise. Nothing outside `app/market/` knows which one is active.

Inputs: [DHANHQ_API](DHANHQ_API.md) (what Dhan offers and its constraints) and [MARKET_SIMULATOR](MARKET_SIMULATOR.md) (the fallback). Extends the existing `backend/app/market/` package (`PriceCache`, `PriceUpdate`, `MarketDataSource`, `SimulatorDataSource`, `MassiveDataSource`, `create_market_data_source`, SSE router). **This is an evolution, not a rewrite**: the push-into-cache architecture from PLAN.md §6 stays.

---

## 1. Requirements and design decisions

| # | Requirement | Decision |
|---|---|---|
| R1 | Backend selects source from env, downstream code agnostic | Keep factory + `MarketDataSource` ABC; add one Dhan implementation |
| R2 | Real-time prices for many tickers | Source pushes into `PriceCache`; SSE reads the cache (unchanged) |
| R3 | End-of-day prices for many tickers | New on-demand API: `get_daily_bars()` and `get_eod_closes()` |
| R4 | "Unsupported tickers are rejected" (PLAN §8) | New `is_supported()`/`resolve()` check used by watchlist and trade routes |
| R5 | % change is vs **previous close** (PLAN §2, §6) | `PriceUpdate` gains `previous_close`; both sources populate it |
| R6 | Works with no keys, deterministic for tests | Simulator is the default and is seedable |
| R7 | Dhan ≠ US markets | Per-source `currency` and default watchlist; unresolvable tickers degrade gracefully |
| R8 | One asyncio app | Async httpx client (not the sync `dhanhq` SDK); no threads except the cache lock |

**Why not use the `dhanhq` SDK?** It is synchronous (`requests`), prints to stdout, converts exceptions into `{"status":"failure"}` dicts, and injects `dhanClientId` into bodies. We need three REST endpoints and a few binary parsers; a ~150-line async client is smaller than adapting the SDK and is testable with `httpx.MockTransport`. The SDK remains the reference for payloads (DHANHQ_API.md).

---

## 2. Configuration and source selection

| Variable | Required | Meaning |
|---|---|---|
| `DHANHQ_API_KEY` | selects Dhan | Dhan **access token** (JWT). Non-empty ⇒ Dhan mode |
| `DHANHQ_CLIENT_ID` | with the above | Dhan client ID. Dhan needs *both* credentials; missing ⇒ startup error |
| `DHANHQ_BASE_URL` | no (default `https://api.dhan.co/v2`) | Override the REST base. **Do not point at `https://sandbox.dhan.co/v2` for prices**: the sandbox has no `/marketfeed/*` endpoints (404, confirmed) and only serves trading + `/charts/*` (DHANHQ_API.md §2.2); the factory logs a warning |
| `DHANHQ_POLL_INTERVAL` | no (default `2.0`) | Seconds between quote polls; clamped to ≥ 1.0 (Quote API limit is 1 req/s) |
| `DHANHQ_CACHE_DIR` | no (default `/app/db`) | Where the downloaded NSE instrument list is cached (the Docker volume) |
| `MASSIVE_API_KEY` | no | Legacy source; kept only for backward compatibility (see below) |
| `MARKET_SEED` | no | Integer; makes the simulator deterministic (tests/demos) |

Selection precedence, evaluated once at startup in `create_market_data_source(cache)`:

```text
DHANHQ_API_KEY set  ──► DhanDataSource    (fail fast if DHANHQ_CLIENT_ID missing)
else MASSIVE_API_KEY ─► MassiveDataSource (legacy; no EOD support → CapabilityError)
else                 ─► SimulatorDataSource
```

Failing fast on a half-configured Dhan setup is deliberate: silently falling back to simulated prices when the user believes they are on real data is worse than refusing to start. Runtime failures (expired token, outage) are different; they degrade (§9) and are visible via `/api/health`.

Open decision for the owner: whether to keep Massive at all. PLAN.md §5/§6 currently names it as the optional real-data source. If Dhan replaces it, delete `massive_client.py` and the `massive` dependency, and update PLAN.md §1/§5/§6. This doc keeps it as a third tier so nothing breaks in the meantime.

---

## 3. Architecture

```text
                       ┌────────────────────────────────────────────┐
 .env ───────────────► │ create_market_data_source(cache)  (factory)│
                       └──────────────┬─────────────────────────────┘
                                      │ returns one MarketDataSource
          ┌───────────────────────────┼─────────────────────────────┐
          ▼                           ▼                             ▼
  DhanDataSource              SimulatorDataSource            MassiveDataSource
  ├─ DhanClient (REST)        ├─ GBMSimulator                (legacy)
  ├─ InstrumentResolver       └─ SyntheticHistory
  ├─ polling task
  └─ [phase 2] feed streams
          │ push                       │ push
          ▼                            ▼
       ┌───────────────── PriceCache (latest PriceUpdate per ticker) ─────────────┐
       └──────┬───────────────────────────────┬───────────────────────┬───────────┘
              ▼                               ▼                       ▼
        SSE /api/stream/prices      portfolio valuation       trade execution (price)

 On-demand (pull) path, same source object:
   source.is_supported(t) / source.get_quotes([...]) / source.get_daily_bars(t, start, end)
        ▲                          ▲
   POST /api/watchlist       GET /api/…/history (future), AI context
```

Two access patterns, deliberately separate:

1. **Streaming (hot path):** the source's background task writes every priced ticker into the `PriceCache`; consumers *only* read the cache. Unchanged.
2. **Request/response (cold path):** validation of a new ticker, snapshot quotes and daily bars. These hit the provider (Dhan) or are computed (simulator) and are rate-limited internally.

---

## 4. Data models (`app/market/models.py`)

`PriceUpdate` is extended **backward-compatibly** (new fields have defaults; existing `to_dict()` consumers keep working). `Bar` is new.

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of one ticker's price."""

    ticker: str
    price: float
    previous_price: float                      # previous *tick* (drives the flash animation)
    timestamp: float = field(default_factory=time.time)   # Unix seconds
    previous_close: float | None = None        # previous session close (drives "% change")

    # change / change_percent / direction: unchanged (tick-to-tick)

    @property
    def day_change(self) -> float | None:
        if self.previous_close is None:
            return None
        return round(self.price - self.previous_close, 4)

    @property
    def day_change_percent(self) -> float | None:
        if not self.previous_close:
            return None
        return round((self.price - self.previous_close) / self.previous_close * 100, 4)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "previous_close": self.previous_close,
            "day_change_percent": self.day_change_percent,
        }


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV candle. `date` is the exchange-local trading date."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "open": self.open, "high": self.high,
                "low": self.low, "close": self.close, "volume": self.volume}
```

Why two "previous" concepts? The PLAN asks for the flash animation (tick vs tick, `previous_price`) *and* the watchlist/positions "% change vs previous close". Today's cache only has the former. The frontend should show `day_change_percent` in the watchlist and positions table and keep `direction` for the flash.

`PriceCache.update` gains an optional `previous_close` parameter; the cache **remembers the last known value per ticker** so a source need not pass it on every tick:

```python
def update(self, ticker, price, timestamp=None, previous_close=None) -> PriceUpdate:
    with self._lock:
        ts = timestamp or time.time()
        prev = self._prices.get(ticker)
        previous_price = prev.price if prev else price
        if previous_close is None and prev is not None:
            previous_close = prev.previous_close          # carry forward
        update = PriceUpdate(ticker=ticker, price=round(price, 2),
                             previous_price=round(previous_price, 2), timestamp=ts,
                             previous_close=None if previous_close is None else round(previous_close, 2))
        self._prices[ticker] = update
        self._version += 1
        return update
```

---

## 5. The interface (`app/market/interface.py`)

The existing lifecycle methods are unchanged. New capabilities are **concrete methods that raise `CapabilityError` by default**, so `MassiveDataSource` keeps working untouched and each source opts in.

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from .models import Bar, PriceUpdate


class MarketDataError(Exception):
    """Base class for market-data failures surfaced to callers."""


class CapabilityError(MarketDataError):
    """This source cannot do what was asked (e.g. EOD history for a US ticker on Dhan)."""


class UnknownTickerError(MarketDataError):
    """Ticker cannot be priced by the active source."""


class MarketDataSource(ABC):
    # ---- metadata -------------------------------------------------------
    name: str = "unknown"          # "dhanhq" | "simulator" | "massive"
    currency: str = "USD"          # ISO code the prices are quoted in

    # ---- lifecycle + streaming (existing) --------------------------------
    @abstractmethod
    async def start(self, tickers: list[str]) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def add_ticker(self, ticker: str) -> None: ...
    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None: ...
    @abstractmethod
    def get_tickers(self) -> list[str]: ...

    # ---- NEW: validation -------------------------------------------------
    async def is_supported(self, ticker: str) -> bool:
        """True if this source can price `ticker`. Cheap; no network on the hot path."""
        return True

    # ---- NEW: on-demand snapshots (cold path) -----------------------------
    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """Latest price for many tickers in one shot. Unsupported tickers are omitted.

        Does NOT require the tickers to be in the streaming set, and does not write
        to the PriceCache. For the tickers already streaming, prefer the cache.
        """
        raise CapabilityError(f"{self.name} does not support get_quotes")

    # ---- NEW: end of day ---------------------------------------------------
    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        """Daily OHLCV bars for `start <= trading date <= end`, ascending. May be empty."""
        raise CapabilityError(f"{self.name} does not support get_daily_bars")

    async def get_eod_closes(self, tickers: list[str], on: date | None = None) -> dict[str, float]:
        """Closing price for many tickers on trading date `on` (default: latest completed
        session). Tickers without data are omitted. Default impl fans out get_daily_bars."""
        raise CapabilityError(f"{self.name} does not support get_eod_closes")
```

Notes:

- Names say *what*, not *how*: callers never see security IDs, segments or CSVs.
- `get_quotes` and `get_eod_closes` take **lists** because both providers batch efficiently (Dhan: 1 call/≤1000 ids; history: N calls under a throttle) and the batching belongs behind the interface.
- Prices are `float` rounded to 2 dp at the cache boundary. Currency is a property of the source, not of each quote.
- Missing data is **omitted or empty, not zero**. A zero price would corrupt portfolio valuation.

### Typical call sites

```python
# POST /api/watchlist: reject unsupported tickers (PLAN §8)
ticker = body.ticker.upper().strip()
if not await source.is_supported(ticker):
    raise HTTPException(422, f"Unsupported ticker: {ticker}")
await source.add_ticker(ticker)

# trade execution: always price from the cache; fall back to a one-off quote
price = cache.get_price(ticker)
if price is None:
    quotes = await source.get_quotes([ticker])
    if ticker not in quotes:
        raise HTTPException(422, f"No price available for {ticker}")
    price = quotes[ticker].price

# EOD for a set of tickers (e.g. nightly valuation or a history endpoint)
closes = await source.get_eod_closes(["TCS", "INFY", "RELIANCE"])     # {"TCS": 3912.4, ...}
bars = await source.get_daily_bars("TCS", date(2026, 9, 1), date(2026, 10, 21))
```

---

## 6. Dhan implementation

### 6.1 Module layout

```text
app/market/
├── models.py          PriceUpdate (+previous_close), Bar
├── cache.py           PriceCache (+previous_close carry-forward)
├── interface.py       MarketDataSource, MarketDataError, CapabilityError, UnknownTickerError
├── factory.py         create_market_data_source()  (+ default_watchlist())
├── simulator.py       GBMSimulator, SimulatorDataSource   (see MARKET_SIMULATOR.md)
├── synthetic_history.py   deterministic daily bars for the simulator
├── seed_prices.py     per-profile seed prices & params
├── massive_client.py  (legacy)
├── stream.py          SSE router (unchanged)
└── dhan/
    ├── __init__.py
    ├── client.py      DhanClient: async REST + throttling + error mapping
    ├── instruments.py InstrumentResolver: ticker ↔ (segment, security_id), CSV cache
    └── source.py      DhanDataSource: lifecycle, polling loop, previous close, EOD
```

### 6.2 `DhanClient`: thin, async, rate-limited

```python
# app/market/dhan/client.py
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


class DhanError(MarketDataError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status, self.code = status, code


class DhanAuthError(DhanError): ...         # bad/expired token, client id, or no Data API subscription
class DhanRateLimited(DhanError): ...       # 429 / DH-904 / 805 (retry after backoff)
class DhanNoData(DhanError): ...            # DH-907: no data for the request

# Error codes from the official Annexure (DHANHQ_API.md §10)
_AUTH_CODES = {"DH-901", "DH-902", "806", "807", "808", "809", "810"}
_RATE_CODES = {"DH-904", "805"}


def _error_code(r: httpx.Response) -> tuple[str | None, str]:
    """Dhan has two error body shapes:
    trading/charts: {"errorType","errorCode":"DH-901","errorMessage"}
    quote:          {"data": {"808": "message"}, "status": "failed"}
    """
    try:
        body = r.json()
    except ValueError:
        return None, r.text[:200]
    if isinstance(body, dict):
        if body.get("errorCode"):
            return str(body["errorCode"]), str(body.get("errorMessage", ""))
        data = body.get("data")
        if body.get("status") == "failed" and isinstance(data, dict) and data:
            code, msg = next(iter(data.items()))
            return str(code), str(msg)
    return None, r.text[:200]


class _Throttle:
    """Allow at most one call per `min_interval` seconds across concurrent tasks."""

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

    def __init__(self, client_id: str, access_token: str, *,
                 base_url: str | None = None,
                 http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(
            base_url=base_url or self.BASE_URL,
            headers={"access-token": access_token, "client-id": client_id,
                     "Content-Type": "application/json", "Accept": "application/json"},
            timeout=httpx.Timeout(10.0),
        )
        self._quote_gate = _Throttle(1.05)    # Quote APIs: 1 req/s
        self._data_gate = _Throttle(0.25)     # Data APIs: 5 req/s

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict, gate: _Throttle) -> dict:
        await gate.wait()
        try:
            r = await self._http.post(path, json=body)
        except httpx.HTTPError as e:                       # network/timeout
            raise DhanError(f"{path}: {e.__class__.__name__}: {e}") from e
        if r.status_code >= 400:
            code, msg = _error_code(r)
            detail = f"{path}: HTTP {r.status_code} {code or ''} {msg}".strip()
            if r.status_code == 429 or code in _RATE_CODES:
                raise DhanRateLimited(detail, status=r.status_code, code=code)
            if r.status_code in (401, 403) or code in _AUTH_CODES:
                raise DhanAuthError(detail, status=r.status_code, code=code)
            if code == "DH-907":
                raise DhanNoData(detail, status=r.status_code, code=code)
            raise DhanError(detail, status=r.status_code, code=code)
        return r.json()

    # -- quotes -----------------------------------------------------------
    async def ohlc(self, securities: dict[str, list[int]]) -> dict[str, dict[int, dict]]:
        """{segment: [ids]} -> {segment: {security_id(int): {last_price, ohlc{...}}}}.
        Splits into chunks of <=1000 ids per request (API limit)."""
        out: dict[str, dict[int, dict]] = {}
        for segment, ids in securities.items():
            for i in range(0, len(ids), 1000):
                chunk = ids[i:i + 1000]
                body = await self._post("/marketfeed/ohlc", {segment: chunk}, self._quote_gate)
                for sec_id, q in (body.get("data", {}).get(segment) or {}).items():
                    out.setdefault(segment, {})[int(sec_id)] = q
        return out

    # -- history -----------------------------------------------------------
    async def daily_bars(self, security_id: int, segment: str, start: date, end: date,
                         instrument: str = "EQUITY") -> list[Bar]:
        try:
            body = await self._post("/charts/historical", {
            "securityId": str(security_id),
            "exchangeSegment": segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
            "fromDate": start.isoformat(),
            "toDate": (end + timedelta(days=1)).isoformat(),   # toDate is non-inclusive (docs)
            }, self._data_gate)
        except DhanNoData:
            return []
        bars: list[Bar] = []
        for i, ts in enumerate(body.get("timestamp") or []):
            day = datetime.fromtimestamp(ts, IST).date()
            if start <= day <= end:
                bars.append(Bar(day, body["open"][i], body["high"][i], body["low"][i],
                                body["close"][i], int(body["volume"][i])))
        return bars
```

### 6.3 `InstrumentResolver`: ticker ↔ security ID

Responsibilities: download Dhan's NSE equity instrument list (`GET /v2/instrument/NSE_EQ`, no auth, follows a redirect to S3; the deployment needs egress to `api.dhan.co` and `s3.ap-south-1.amazonaws.com`), cache it under `DHANHQ_CACHE_DIR` (refresh if older than 24 h), keep `EQUITY` rows in series `EQ`, and expose `resolve(ticker) -> Instrument | None`. It **asserts the CSV header** so a format change fails loudly at startup rather than yielding an empty map.

```python
# app/market/dhan/instruments.py
from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)
# Segment-wise list: no auth, ~1.6 MB, 302-redirects to a pre-signed S3 URL (follow redirects).
# Always the production host, even if DHANHQ_BASE_URL is overridden.
NSE_EQ_URL = "https://api.dhan.co/v2/instrument/NSE_EQ"
_REQUIRED = {"EXCH_ID", "SEGMENT", "SECURITY_ID", "INSTRUMENT", "SERIES", "UNDERLYING_SYMBOL"}


@dataclass(frozen=True, slots=True)
class Instrument:
    ticker: str          # exchange symbol, e.g. "TCS" (UNDERLYING_SYMBOL)
    security_id: int
    segment: str         # "NSE_EQ"
    instrument: str      # "EQUITY"
    name: str = ""       # DISPLAY_NAME, e.g. "Tata Consultancy Services"


class InstrumentResolver:
    def __init__(self, cache_dir: Path, max_age_s: float = 86_400) -> None:
        self._path = Path(cache_dir) / "dhan-nse-eq-instruments.csv"
        self._max_age = max_age_s
        self._by_ticker: dict[str, Instrument] = {}
        self._by_key: dict[tuple[str, int], Instrument] = {}

    async def load(self) -> None:
        text = await self._read_or_download()
        reader = csv.DictReader(io.StringIO(text))
        missing = _REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Dhan instrument list format changed; missing columns: {sorted(missing)}")
        for row in reader:
            # The file also has INDEX rows and non-EQ series (SG, SM, BE, ...). EQUITY+EQ is unique per symbol.
            if (row["EXCH_ID"] == "NSE" and row["SEGMENT"] == "E"
                    and row["INSTRUMENT"] == "EQUITY" and row["SERIES"] == "EQ"):
                inst = Instrument(row["UNDERLYING_SYMBOL"].strip().upper(),
                                  int(row["SECURITY_ID"]), "NSE_EQ", "EQUITY",
                                  row.get("DISPLAY_NAME", "").strip())
                self._by_ticker.setdefault(inst.ticker, inst)
                self._by_key[(inst.segment, inst.security_id)] = inst
        logger.info("Dhan instrument master loaded: %d NSE equities", len(self._by_ticker))

    def resolve(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker.upper())

    def by_key(self, segment: str, security_id: int) -> Instrument | None:
        return self._by_key.get((segment, security_id))

    async def _read_or_download(self) -> str:
        if self._path.exists() and time.time() - self._path.stat().st_mtime < self._max_age:
            return self._path.read_text()
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            r = await http.get(NSE_EQ_URL)
            r.raise_for_status()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(r.text)
        except OSError:
            logger.warning("Could not cache Dhan instrument list at %s", self._path)
        return r.text
```

Security IDs for the ten default NSE tickers were verified against the live list (DHANHQ_API.md §5). Phase 2 adds a second resolver for US stocks (`INX_EQ`, global CSV) behind the same `resolve()` shape; `Instrument.segment` then routes to the right transport.

### 6.4 `DhanDataSource`: lifecycle, polling, previous close, EOD

Key behaviours:

- **One quote call per cycle** for all priced tickers (grouped by segment), at most once per `poll_interval` (≥ 1 s).
- Writes `PriceCache.update(ticker, last_price, previous_close=…)`. The SSE layer re-sends the cache every ~500 ms, so a 2 s poll still produces a flowing UI; the flash animation fires on actual changes only.
- **Previous close** comes from daily history, not from `ohlc.close`. For each ticker we fetch the last ~10 calendar days once (on `start`/`add_ticker`, and again on IST date rollover) and take the latest bar dated **before today (IST)**. `ohlc.close` is only used as a fallback *after* the history lookup for that ticker has finished without a result (so a startup race can't briefly show a wrong day change), because its after-hours semantics are unverified (DHANHQ_API.md §6). Cost: N history calls at 5/s (10 tickers ≈ 2 s, in a background task so `start()` doesn't block). A cheaper alternative to evaluate in the smoke test: poll `/marketfeed/quote` instead of `/ohlc` and take `previous_close = last_price − net_change` (documented as change vs previous day's close); it would remove the N startup history calls but is unverified for `NSE_EQ` (DHANHQ_API.md §12).
- **Market hours:** NSE cash session is 09:15–15:30 IST, Mon–Fri. Outside it, poll every 30 s (prices are static; one poll per cycle keeps the cache warm and detects a token problem). Exchange holidays are not modelled; Dhan simply returns the last price.
- **Failure policy:** `DhanRateLimited` → double the interval (cap 30 s) then recover; `DhanAuthError` → set `healthy=False`, log once at ERROR, poll every 60 s (so a renewed token via restart/refresh recovers); other `DhanError` → log, keep last cached prices (stale but visible), retry next cycle. The loop never raises.

```python
# app/market/dhan/source.py
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from ..cache import PriceCache
from ..interface import CapabilityError, MarketDataSource
from ..models import Bar, PriceUpdate
from .client import IST, DhanAuthError, DhanClient, DhanError, DhanRateLimited
from .instruments import Instrument, InstrumentResolver

logger = logging.getLogger(__name__)


def market_is_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


class DhanDataSource(MarketDataSource):
    name = "dhanhq"
    currency = "INR"

    def __init__(self, client_id: str, access_token: str, price_cache: PriceCache,
                 cache_dir: Path, poll_interval: float = 2.0, *,
                 base_url: str | None = None,
                 client: DhanClient | None = None,
                 resolver: InstrumentResolver | None = None) -> None:
        self._cache = price_cache
        self._client = client or DhanClient(client_id, access_token, base_url=base_url)
        self._resolver = resolver or InstrumentResolver(cache_dir)
        self._interval = max(1.0, poll_interval)
        self._tickers: dict[str, Instrument] = {}      # active, resolved tickers
        self._prev_close: dict[str, float] = {}
        self._prev_close_tried: set[str] = set()       # history lookup finished (ok or failed)
        self._prev_close_day: date | None = None
        self._task: asyncio.Task | None = None
        self._bg: set[asyncio.Task] = set()
        self.healthy = True

    # ---- lifecycle ---------------------------------------------------------
    async def start(self, tickers: list[str]) -> None:
        await self._resolver.load()
        for t in tickers:
            self._track(t)
        # The loop's first iteration sees _prev_close_day is None and kicks off the refresh.
        self._task = asyncio.create_task(self._run_loop(), name="dhan-poll")

    async def stop(self) -> None:
        for task in [self._task, *self._bg]:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in [self._task, *self._bg] if t], return_exceptions=True)
        self._task = None
        await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        if self._track(ticker):
            self._spawn(self._refresh_prev_close([ticker.upper()]))
            self._spawn(self._poll_once())        # price appears without waiting a full cycle

    async def remove_ticker(self, ticker: str) -> None:
        t = ticker.upper()
        self._tickers.pop(t, None)
        self._prev_close.pop(t, None)
        self._prev_close_tried.discard(t)
        self._cache.remove(t)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def is_supported(self, ticker: str) -> bool:
        return self._resolver.resolve(ticker) is not None

    # ---- on-demand ----------------------------------------------------------
    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        insts = {t.upper(): self._resolver.resolve(t) for t in tickers}
        raw = await self._client.ohlc(_group([i for i in insts.values() if i]))
        out: dict[str, PriceUpdate] = {}
        for t, inst in insts.items():
            q = raw.get(inst.segment, {}).get(inst.security_id) if inst else None
            if q and q.get("last_price"):
                prev = self._prev_close.get(t) or (q.get("ohlc") or {}).get("close")
                out[t] = PriceUpdate(t, round(q["last_price"], 2), round(q["last_price"], 2),
                                     previous_close=prev)
        return out

    async def get_daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        inst = self._resolver.resolve(ticker)
        if inst is None:
            return []
        return await self._client.daily_bars(inst.security_id, inst.segment, start, end,
                                             inst.instrument)

    async def get_eod_closes(self, tickers: list[str], on: date | None = None) -> dict[str, float]:
        end = on or (datetime.now(IST).date() - timedelta(days=0 if not market_is_open() else 1))
        start = end - timedelta(days=7)               # cover weekends/holidays
        results = await asyncio.gather(*(self.get_daily_bars(t, start, end) for t in tickers),
                                       return_exceptions=True)
        out: dict[str, float] = {}
        for t, bars in zip(tickers, results):
            if isinstance(bars, Exception):
                logger.warning("EOD fetch failed for %s: %s", t, bars)
            elif bars:
                out[t.upper()] = bars[-1].close      # latest session on/before `end`
        return out

    # ---- internals ------------------------------------------------------------
    def _track(self, ticker: str) -> bool:
        t = ticker.upper()
        inst = self._resolver.resolve(t)
        if inst is None:
            logger.warning("Dhan: %s is not a known NSE equity; it will have no price", t)
            return False
        if t in self._tickers:
            return False
        self._tickers[t] = inst
        return True

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _refresh_prev_close(self, tickers: list[str]) -> None:
        today = datetime.now(IST).date()
        self._prev_close_day = today          # set first so the loop doesn't respawn us
        for t in tickers:
            inst = self._tickers.get(t)
            if inst is None:
                continue
            try:
                bars = await self._client.daily_bars(inst.security_id, inst.segment,
                                                     today - timedelta(days=10), today,
                                                     inst.instrument)
            except DhanError as e:
                logger.warning("Dhan: previous close for %s unavailable: %s", t, e)
                self._prev_close_tried.add(t)
                continue
            prior = [b for b in bars if b.date < today]
            if prior:
                self._prev_close[t] = prior[-1].close
            self._prev_close_tried.add(t)

    async def _poll_once(self) -> None:
        active = dict(self._tickers)
        if not active:
            return
        raw = await self._client.ohlc(_group(list(active.values())))
        self.healthy = True
        for t, inst in active.items():
            q = raw.get(inst.segment, {}).get(inst.security_id)
            if not q or not q.get("last_price"):
                continue                                  # keep last cached price; never write 0
            prev = self._prev_close.get(t)
            if prev is None and t in self._prev_close_tried:      # history failed: use ohlc.close
                prev = (q.get("ohlc") or {}).get("close")
            self._cache.update(t, float(q["last_price"]), previous_close=prev)

    async def _run_loop(self) -> None:
        delay = self._interval
        while True:
            try:
                if datetime.now(IST).date() != self._prev_close_day:     # day rollover
                    self._spawn(self._refresh_prev_close(list(self._tickers)))
                await self._poll_once()
                delay = self._interval if market_is_open() else 30.0
            except asyncio.CancelledError:
                raise
            except DhanRateLimited:
                delay = min(delay * 2, 30.0)
                logger.warning("Dhan rate limited; next poll in %.0fs", delay)
            except DhanAuthError as e:
                if self.healthy:
                    logger.error("Dhan authentication failed (token expired?): %s", e)
                self.healthy = False
                delay = 60.0
            except Exception:
                logger.exception("Dhan poll failed")
                delay = min(max(delay, self._interval) * 2, 30.0)
            await asyncio.sleep(delay)


def _group(insts: list[Instrument]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for i in insts:
        grouped.setdefault(i.segment, []).append(i.security_id)
    return grouped
```

(`CapabilityError` is imported for the phase-2 US path; unused imports should be pruned when this is implemented under `ruff`.)

### 6.5 Phase 2: WebSocket push and US stocks

Not needed for MVP. Hooks if/when wanted:

- `DhanDataSource` gains `use_websocket: bool`; a `DhanFeedStream` task (DHANHQ_API.md §8.4) replaces `_run_loop`, mapping `(segment_code, security_id)` back via `resolver.by_key()` and writing `cache.update(...)`. The prev-close packet (code 6) then replaces the history-derived value. Keep the REST poll as a 30 s reconciliation.
- US tickers: a second resolver over the global CSV and a `GlobalFeedStream`; `get_daily_bars` for `INX_EQ` raises `CapabilityError` until a historical endpoint is confirmed. Currency becomes per-instrument (`INR`/`USD`), which needs `Instrument.currency` and a UI that tolerates mixed currencies (portfolio totals would need FX). **Recommendation: do not mix; pick the Indian universe in Dhan mode.**

---

## 7. Factory and default watchlist (`app/market/factory.py`)

```python
import logging
import os
from pathlib import Path

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

US_DEFAULTS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
NSE_DEFAULTS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
                "BHARTIARTL", "ITC", "LT", "HINDUNILVR"]


def _dhan_credentials() -> tuple[str, str] | None:
    token = os.environ.get("DHANHQ_API_KEY", "").strip()
    if not token:
        return None
    client_id = os.environ.get("DHANHQ_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("DHANHQ_API_KEY is set but DHANHQ_CLIENT_ID is missing; "
                           "Dhan requires both. Unset DHANHQ_API_KEY to use the simulator.")
    return client_id, token


def default_watchlist() -> list[str]:
    """Seed watchlist for a fresh database; depends on the active source's market."""
    return NSE_DEFAULTS if _dhan_credentials() else US_DEFAULTS


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    creds = _dhan_credentials()
    if creds:
        from .dhan.source import DhanDataSource            # lazy: keeps httpx/CSV cost out of sim mode
        client_id, token = creds
        base_url = os.environ.get("DHANHQ_BASE_URL") or None
        if base_url and "sandbox" in base_url:
            logger.warning("DHANHQ_BASE_URL is the Dhan sandbox, which has no /marketfeed/* quote "
                           "endpoints: live prices will not work (history/auth only)")
        logger.info("Market data source: DhanHQ (real data, INR)")
        return DhanDataSource(
            client_id, token, price_cache,
            cache_dir=Path(os.environ.get("DHANHQ_CACHE_DIR", "/app/db")),
            poll_interval=float(os.environ.get("DHANHQ_POLL_INTERVAL", "2.0")),
            base_url=base_url,
        )
    if os.environ.get("MASSIVE_API_KEY", "").strip():
        from .massive_client import MassiveDataSource
        logger.info("Market data source: Massive API (legacy)")
        return MassiveDataSource(api_key=os.environ["MASSIVE_API_KEY"].strip(),
                                 price_cache=price_cache)
    from .simulator import SimulatorDataSource
    logger.info("Market data source: GBM simulator")
    seed = os.environ.get("MARKET_SEED")
    return SimulatorDataSource(price_cache=price_cache, seed=int(seed) if seed else None)
```

`backend/db` seeding must call `default_watchlist()` instead of hard-coding the ten US tickers. A database that was seeded under the simulator and later started with a Dhan key will contain US tickers that Dhan cannot price; see §9 for how they degrade.

---

## 8. Consumer-facing behaviour

| Consumer | Change needed |
|---|---|
| SSE stream (`stream.py`) | Nothing structural: `PriceUpdate.to_dict()` now includes `previous_close`, `day_change_percent` |
| `GET /api/watchlist`, `GET /api/portfolio` | Return `day_change_percent`; show `—` when `None` |
| `POST /api/watchlist` | Call `source.is_supported()` before insert (R4) |
| Trade execution | Price from cache; fall back to `get_quotes`; reject if no price |
| `/api/health` | Include `{"market": {"source": source.name, "currency": source.currency, "healthy": getattr(source, "healthy", True)}}` |
| Frontend | Format currency using `currency` (₹ vs $); label the active source in the header |
| LLM context | Include currency so the assistant doesn't talk dollars while holding INR stocks |

---

## 9. Error handling and degradation

| Situation | Behaviour |
|---|---|
| Both Dhan creds not set properly | Startup error with actionable message |
| Token expired mid-run | `healthy=False`, ERROR logged once, last prices stay in cache (SSE keeps sending stale values; **timestamps stop advancing so the UI can show "stale"**), poll retries every 60 s |
| 429 | Interval doubles up to 30 s, then recovers |
| Ticker not in the instrument list (or not series `EQ`) | `is_supported()` false; if it came from an old DB it is skipped with a WARNING and has no cache entry → API returns no price → UI shows `—`; trades on it are rejected |
| Market closed | 30 s poll; prices flat; `day_change_percent` is vs. previous close so it still shows the last session's move |
| History call fails | `previous_close` falls back to `ohlc.close`; if absent, `None` |
| Instrument list download fails and no cached copy | Startup error (cannot resolve anything); with a cached copy of any age we use it and warn |

Stale detection: expose `PriceUpdate.timestamp` age; the frontend greys prices older than, say, 15 s while the connection dot stays green. This keeps "connected to our server" distinct from "data is live".

---

## 10. Testing strategy

All offline, all fast; no test needs a Dhan account.

| Test | How |
|---|---|
| `DhanClient` request shapes | `httpx.MockTransport` asserting URL, headers, body (`{"NSE_EQ":[11536]}`; `securityId` is a string for history) |
| Response parsing | Fixture JSON for ohlc and historical (copy from the smoke test in DHANHQ_API.md §11 once verified) |
| Chunking | 2,500 ids ⇒ 3 requests |
| Throttle | Fake `time.monotonic`/`sleep`: two calls ≥ 1.05 s apart |
| Error mapping | **both body shapes**: `{"errorCode":"DH-901"}` and `{"data":{"808":"…"},"status":"failed"}` → `DhanAuthError`; `DH-904`/`805`/429 → `DhanRateLimited`; `DH-907` on history → empty list; `DH-905` → `DhanError(code=…)` |
| `InstrumentResolver` | Small CSV fixture: `EQUITY`/`EQ` rows kept; `INDEX`, `SG`/`BE` series and non-NSE rows ignored; header assertion fails loudly; redirect followed |
| `DhanDataSource` | Inject fake `DhanClient`/resolver; assert cache writes, never-write-zero, prev-close from history, rollover refresh, backoff on 429, `healthy` flip on auth error |
| Factory | `monkeypatch.setenv`: precedence matrix; missing client id raises |
| Cache | `previous_close` carry-forward; backward-compat `update()` signature |
| Interface contract | One parametrised suite run against **both** `SimulatorDataSource` and a fake-backed `DhanDataSource`: `is_supported`, `get_quotes`, `get_daily_bars` ascending & within range, no zero prices |
| Live (opt-in) | `pytest -m live` marker, skipped unless `DHANHQ_API_KEY` is set; runs the §11 smoke checks |

Binary-feed parsers (phase 2) get table-driven tests built with `struct.pack` using the formats in DHANHQ_API.md §8.3.

---

## 11. Migration steps

1. `models.py` / `cache.py`: add `previous_close`, `Bar` (tests for backward compatibility).
2. `interface.py`: add exceptions, `name`/`currency`, new default-raising methods; Massive untouched.
3. Simulator: `previous_close` = seed price, `synthetic_history.py`, `is_supported`, `get_quotes`, `get_daily_bars`, `get_eod_closes`, seedable RNG (see MARKET_SIMULATOR.md).
4. `dhan/` package + `httpx` dependency (`uv add httpx`). `websockets` only in phase 2.
5. Factory + `default_watchlist()`; wire into DB seeding and `/api/health`.
6. Update `.env.example`, PLAN.md §5/§6 (Dhan vars, Massive status), `backend/CLAUDE.md`, `MARKET_DATA_SUMMARY.md`.
7. Run the Dhan smoke test (DHANHQ_API.md §11) with a real, Data-API-subscribed token against production; fix the [UNVERIFIED] items in DHANHQ_API.md; add fixtures.

---

## 12. Open questions for the project owner

1. **Universe in Dhan mode:** Indian equities in INR (recommended) vs. US stocks via the Global feed (more moving parts; no REST history). The choice affects the default watchlist, the currency symbol and the LLM prompt.
2. **Keep Massive?** Dhan covers the "real data" role; Massive keeps the US-equity real-data path alive.
3. **Token operations:** accept a manually pasted 24 h token (simple, needs a restart or hot-reload when it expires) vs. implementing `RenewToken` / TOTP generation (more credential surface).
4. **Data API subscription:** Data APIs are separately chargeable (DHANHQ_API.md §2.3); confirm the account has it before relying on quotes/history. The sandbox cannot substitute (no quote endpoints).
5. **Poll vs. push:** polling at 2 s is the MVP; confirm that is acceptable before investing in the WebSocket path.
