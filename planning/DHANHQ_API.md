# DhanHQ API Reference (for FinAlly market data)

Research notes on the DhanHQ v2 trading/data APIs, scoped to what FinAlly needs: **real-time prices and end-of-day (EOD) prices for multiple tickers**. Order placement, portfolio, funds, option chain, etc. are out of scope.

Companion docs: [MARKET_INTERFACE.md](MARKET_INTERFACE.md) (the unified Python API built on this) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the fallback when no key is set).

---

## 0. Sources and verification status

The official docs site (`dhanhq.co/docs/v2/`) was **not reachable** from the research environment (blocked by network policy). Facts below are graded by how they were obtained:

| Grade | Meaning | Source |
|---|---|---|
| **[SDK]** | Read directly from the source of the official `dhanhq` Python SDK, v2.3.0 (PyPI) | Endpoints, payload keys, headers, WebSocket URLs, binary packet layouts, segment codes |
| **[DOCS]** | Seen in search-result excerpts of the official docs / Dhan support pages | Base URL, rate limits, 1000-instrument cap, WebSocket limits, sample response keys |
| **[UNVERIFIED]** | From memory of the docs or inferred; **must be confirmed against a live account before relying on it** | Anything so marked |

Before implementing, run the smoke test in §11 with a real token. It exercises every [UNVERIFIED] item that matters.

**Interactive API references (Swagger UI), not readable from the research environment:**

| Environment | URL |
|---|---|
| Production | <https://api.dhan.co/v2/#/> |
| Sandbox | <https://sandbox.dhan.co/v2/#/> |

Both hosts were rejected by the environment's network policy (HTTP 403 at the proxy), so this document has **not** been cross-checked against them. Once `api.dhan.co` and `sandbox.dhan.co` are allowed (or someone pastes the Swagger JSON/pages), the request/response schemas in §6, §7 and §10 and every [UNVERIFIED] tag should be re-checked against them.

Official references to re-check: <https://dhanhq.co/docs/v2/> (Market Quote, Historical Data, Live Market Feed, Instruments, Annexure), <https://dhanhq.co/docs/DhanHQ-py/>, <https://github.com/dhan-oss/DhanHQ-py>.

---

## 1. Scope and the key fit problem

**DhanHQ is an Indian broker API.** Its market-data surface covers:

- NSE / BSE equities, indices, F&O, currency; MCX commodities (REST + WebSocket) **[SDK]**
- A newer **Global Stocks (US)** module (`INX_EQ` segment). In SDK 2.3.0 its market data is **WebSocket only** (no REST LTP/OHLC/history calls exist in the SDK) **[SDK]**

FinAlly's default watchlist is US tickers (AAPL, GOOGL, …) priced in USD. Consequences:

1. With DhanHQ, the natural universe is **NSE equities in INR** (RELIANCE, TCS, INFY, …).
2. US tickers are only reachable through the Global Stocks WebSocket feed, and its availability depends on the account (US-stocks enablement). Historical/EOD for US stocks has **no documented REST endpoint in the SDK**.
3. Every ticker must be mapped to a numeric **security ID** via Dhan's instrument master files (§5). Dhan APIs do not accept symbols like `"TCS"` directly.

These drive the design choices in MARKET_INTERFACE.md (symbol resolver, `currency`, per-mode default watchlist, capability errors).

---

## 2. Authentication

**Two credentials are required**, not one:

| Credential | Header / param | Notes |
|---|---|---|
| Client ID (`dhanClientId`) | `client-id` header | Numeric string identifying the account |
| Access token (JWT) | `access-token` header | Valid for **24 hours** **[DOCS/UNVERIFIED]**; generated from web.dhan.co → My Profile → DhanHQ Trading APIs, or via the auth flow below |

> The task's `DHANHQ_API_KEY` env var maps to the **access token**. A companion `DHANCLIENT_ID`-style variable is mandatory; this project names it `DHANHQ_CLIENT_ID` (see MARKET_INTERFACE.md §2).

Base URLs:

- REST (production): `https://api.dhan.co/v2` **[SDK]**
- REST (sandbox): `https://sandbox.dhan.co/v2` **[provided by the project owner; not verified]**
- Auth server: `https://auth.dhan.co` **[SDK]**

**Sandbox: what is and isn't known.** A secondary source describes Dhan's sandbox as a place to test API requests/responses and order workflows *without real market trades*, not as live-market paper trading. Whether the sandbox serves **market quotes, historical candles or the live WebSocket feed**, whether it needs separate credentials/tokens, and whether its prices are real, static or synthetic are all **unknown**. Do not assume it can substitute for production market data; the smoke test in §11 should be run against the sandbox base URL too and the result recorded here. The client in MARKET_INTERFACE.md takes the base URL from configuration, so switching is a one-line env change.

Headers on every REST call **[SDK]**:

```http
access-token: <JWT>
client-id: <client id>
Content-Type: application/json
Accept: application/json
```

A **Data APIs subscription** is required for market quotes, history and the live feed; without it the server returns error 806 ("Data APIs not subscribed") **[SDK for the WS code; pricing UNVERIFIED]**. Trading APIs are free; Data APIs have historically been a paid add-on. Check current pricing.

### Token lifecycle **[SDK]**

```text
GET  https://api.dhan.co/v2/RenewToken        headers: access-token, dhanClientId
GET  https://api.dhan.co/v2/profile           headers: access-token, dhanClientId   (validity check)
POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=..&pin=..&totp=..     (TOTP-based generation)
POST https://auth.dhan.co/app/generate-consent  (browser consent flow for apps)
```

`RenewToken` only works on a still-valid token (it extends it by another 24h), so a long-running server should renew on a schedule (e.g. every 12h) rather than after expiry. For unattended operation the TOTP route is the only way to mint a fresh token from scratch; that needs the PIN and TOTP secret, which is a heavier credential commitment than this project should require. **Recommendation:** read the token from env, validate with `/profile` at startup, surface expiry loudly (auth errors → health endpoint degraded), and support optional renewal.

---

## 3. Rate limits and quotas

| Bucket | Limit | Applies to |
|---|---|---|
| Quote APIs | **1 request/second** | `/marketfeed/ltp`, `/marketfeed/ohlc`, `/marketfeed/quote` **[DOCS]** |
| Data APIs | **5 requests/second** (also a daily cap, reported as 100,000/day) **[DOCS / daily cap UNVERIFIED]** | `/charts/historical`, `/charts/intraday` |
| Instruments per quote request | **up to 1000** **[DOCS]** | Quote APIs |
| WebSocket connections | **5 per user** **[DOCS]** | Live feed |
| Instruments per WS connection | **5000** **[DOCS]** | Live feed |
| Instruments per WS subscribe message | **100** **[DOCS, SDK batches at 100]** | Live feed |

One community report claimed Data APIs effectively enforce 1 req/s; treat **1 req/s for quotes** as the safe ceiling and throttle history calls client-side.

---

## 4. Exchange segments

String names (REST bodies and JSON subscribe messages) and numeric codes (binary packet headers) **[SDK]**:

| String | Code | Meaning |
|---|---|---|
| `IDX_I` | 0 | Indices |
| `NSE_EQ` | 1 | NSE cash equities |
| `NSE_FNO` | 2 | NSE derivatives |
| `NSE_CURRENCY` | 3 | NSE currency |
| `BSE_EQ` | 4 | BSE cash equities |
| `MCX_COMM` | 5 | MCX commodities |
| `BSE_CURRENCY` | 7 | BSE currency |
| `BSE_FNO` | 8 | BSE derivatives |
| `INX_EQ` | – | Global Stocks (US); the global feed uses string segment names **[SDK]** |

Instrument type strings used by the history endpoints include `EQUITY`, `INDEX`, `FUTIDX`, `OPTIDX`, `FUTSTK`, `OPTSTK`, `FUTCOM`, … **[SDK docstrings / UNVERIFIED for the full list]**. For plain stocks use `EQUITY`.

---

## 5. Instrument master (symbol → security ID)

Dhan publishes CSV scrip masters **[SDK]**:

| File | URL |
|---|---|
| Compact | `https://images.dhan.co/api-data/api-scrip-master.csv` |
| Detailed | `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` |
| Global (US) stocks | `https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv` |

**Compact CSV columns [UNVERIFIED, from memory of the docs; assert the header at load time]:**

`SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID, SEM_INSTRUMENT_NAME, SEM_EXPIRY_CODE, SEM_TRADING_SYMBOL, SEM_LOT_UNITS, SEM_CUSTOM_SYMBOL, SEM_EXPIRY_DATE, SEM_STRIKE_PRICE, SEM_OPTION_TYPE, SEM_TICK_SIZE, SEM_EXPIRY_FLAG`

An NSE cash-equity row is `SEM_EXM_EXCH_ID == "NSE"`, `SEM_SEGMENT == "E"`, `SEM_INSTRUMENT_NAME == "EQUITY"`; its `SEM_SMST_SECURITY_ID` is the security ID and `SEM_TRADING_SYMBOL` the ticker. The API docs' own sample uses `11536` (TCS) in `NSE_EQ` **[SDK docstring]**. Other commonly cited IDs (RELIANCE 2885, INFY 1594, HDFCBANK 1333, SBIN 3045) are **not** to be hard-coded; always resolve from the CSV. The master changes daily (new listings, delistings), so cache it on disk and refresh daily.

**Global CSV columns [SDK docstring]:** `EXCHANGE, SEGMENT, SCRIP_CODE, ISIN_CODE, SYMBOL, SYMBOL_NAME, EXCH_SYMBOL, CUSTOM_SYMBOL, TRADING_SYMBOL, FRACTION, CUSTOM_EXCH, INSTRUMENT_NAME, TICK_SIZE, LOT_SIZE, UPPER_LIMIT, LOWER_LIMIT, UPDATE_DATE`. That `SCRIP_CODE` is the `securityId` for the global feed, and `SYMBOL`/`EXCH_SYMBOL` is the US ticker, is an **[UNVERIFIED]** inference.

```python
import csv, io
import httpx

COMPACT_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

def load_nse_equities() -> dict[str, int]:
    """Return {trading_symbol: security_id} for NSE cash equities."""
    text = httpx.get(COMPACT_URL, timeout=60).text
    out: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row["SEM_EXM_EXCH_ID"] == "NSE" and row["SEM_SEGMENT"] == "E"
                and row["SEM_INSTRUMENT_NAME"] == "EQUITY"):
            out[row["SEM_TRADING_SYMBOL"]] = int(row["SEM_SMST_SECURITY_ID"])
    return out

ids = load_nse_equities()
print(ids["TCS"])   # expect 11536
```

Caveat: one trading symbol can appear under several series/rows (e.g. BE/SM series). If duplicates matter, use the detailed CSV and filter the series column to `EQ`.

---

## 6. Market Quote REST APIs (real-time snapshot, many tickers in one call)

Three endpoints, identical request shape, increasing detail **[SDK]**:

| Endpoint | Returns |
|---|---|
| `POST /v2/marketfeed/ltp` | Last traded price |
| `POST /v2/marketfeed/ohlc` | LTP + day OHLC |
| `POST /v2/marketfeed/quote` | LTP + OHLC + volume, OI, circuit limits, 5-level depth, etc. |

**Request body:** a JSON object mapping **segment → list of numeric security IDs** (no wrapper key) **[SDK + DOCS]**:

```json
{ "NSE_EQ": [11536, 2885], "NSE_FNO": [49081] }
```

Headers: `access-token` and `client-id` (both required). Max 1000 instruments per request, 1 request/second **[DOCS]**.

> The official SDK additionally injects `"dhanClientId"` into every JSON body (including these). A raw client should rely on the `client-id` header; if a request is rejected, adding `dhanClientId` to the body is the first thing to try. **[UNVERIFIED]**

### Response **[DOCS excerpt; field list UNVERIFIED]**

`/marketfeed/ltp`:

```json
{
  "data": { "NSE_EQ": { "11536": { "last_price": 4520.0 } } },
  "status": "success"
}
```

`/marketfeed/ohlc` adds an `ohlc` object per instrument:

```json
{
  "data": {
    "NSE_EQ": {
      "11536": {
        "last_price": 4525.5,
        "ohlc": { "open": 4500.0, "close": 4488.2, "high": 4540.0, "low": 4495.1 }
      }
    }
  },
  "status": "success"
}
```

`/marketfeed/quote` adds (names from memory, **UNVERIFIED**): `average_price`, `buy_quantity`, `sell_quantity`, `depth{buy[],sell[]}`, `last_quantity`, `last_trade_time`, `lower_circuit_limit`, `upper_circuit_limit`, `net_change`, `oi`, `oi_day_high`, `oi_day_low`, `volume`.

Notes:

- **Security IDs are string keys in the response** even though they are ints in the request.
- **`ohlc.close` semantics:** during market hours this is understood to be the *previous session's close*; after the close it is the day's close. **[UNVERIFIED]**: verify with the smoke test, then decide whether to use it as `previous_close` (see MARKET_INTERFACE.md §6.3, which prefers deriving previous close from daily history).
- Outside market hours, LTP is the last traded price (the last close); values stop changing.
- The SDK wraps responses as `{"status", "remarks", "data": <raw JSON>}`, so with the SDK the path is `resp["data"]["data"]["NSE_EQ"]["11536"]["last_price"]` (note the double `data`). A raw HTTP client sees `resp["data"]["NSE_EQ"]...`.

### Raw HTTP example (httpx), many tickers, one call

```python
import httpx

BASE = "https://api.dhan.co/v2"

def make_client(client_id: str, access_token: str) -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers={"access-token": access_token, "client-id": client_id,
                 "Content-Type": "application/json", "Accept": "application/json"},
        timeout=10.0,
    )

def get_ohlc(http: httpx.Client, securities: dict[str, list[int]]) -> dict[str, dict]:
    """securities = {"NSE_EQ": [11536, 2885]} -> {"11536": {...}, "2885": {...}} flattened by id."""
    r = http.post("/marketfeed/ohlc", json=securities)
    r.raise_for_status()
    body = r.json()
    flat: dict[str, dict] = {}
    for _segment, by_id in body["data"].items():
        flat.update(by_id)
    return flat

with make_client("1000000001", "eyJ...") as http:
    quotes = get_ohlc(http, {"NSE_EQ": [11536, 2885]})
    for sec_id, q in quotes.items():
        print(sec_id, q["last_price"], q["ohlc"]["close"])
```

### SDK equivalent

```python
from dhanhq import DhanContext, dhanhq

ctx = DhanContext("1000000001", "eyJ...")
dhan = dhanhq(ctx)

resp = dhan.ohlc_data({"NSE_EQ": [11536, 2885]})   # also ticker_data (LTP) and quote_data
if resp["status"] == "success":
    print(resp["data"]["data"]["NSE_EQ"]["11536"]["last_price"])
else:
    print(resp["remarks"])      # {'error_code':..., 'error_type':..., 'error_message':...}
```

The SDK is **synchronous** (`requests`), swallows exceptions into `{"status": "failure"}` dicts, and prints to stdout. For an asyncio FastAPI app, prefer a thin httpx client over the SDK (the same decision is recorded in MARKET_INTERFACE.md §7).

---

## 7. Historical data REST APIs (end-of-day and intraday candles)

Both are **POST, one instrument per call** **[SDK]**: for N tickers, make N calls under the 5 req/s Data API limit.

### 7.1 Daily candles: `POST /v2/charts/historical`

Body **[SDK]**:

```json
{
  "securityId": "11536",
  "exchangeSegment": "NSE_EQ",
  "instrument": "EQUITY",
  "expiryCode": 0,
  "oi": false,
  "fromDate": "2026-09-01",
  "toDate": "2026-10-21"
}
```

- `expiryCode` is for derivatives; use `0` for equities. (The SDK accepts 0–3; docs annexure reportedly lists 0–2. **[UNVERIFIED]**)
- Dates are `YYYY-MM-DD`. `toDate` is believed to be **exclusive**, so request `end + 1 day` and filter. **[UNVERIFIED]**
- `securityId` is a string in the body.

Response: **column-oriented arrays** of equal length **[DOCS shape, UNVERIFIED in detail]**:

```json
{
  "open":      [4500.0, 4510.5],
  "high":      [4540.0, 4532.0],
  "low":       [4495.1, 4501.0],
  "close":     [4525.5, 4520.0],
  "volume":    [1203345, 987654],
  "timestamp": [1790275200, 1790361600],
  "open_interest": [0, 0]
}
```

`timestamp` is **Unix epoch seconds** (v2 moved off Julian time) **[SDK/search]**. Daily candles are stamped at IST midnight, so convert with an IST timezone to get the trading date. The SDK helper does exactly this (returns a `date` when the IST time is 00:00).

```python
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

def get_daily_bars(http, security_id: int, start: date, end: date,
                   segment="NSE_EQ", instrument="EQUITY") -> list[dict]:
    r = http.post("/charts/historical", json={
        "securityId": str(security_id),
        "exchangeSegment": segment,
        "instrument": instrument,
        "expiryCode": 0,
        "oi": False,
        "fromDate": start.isoformat(),
        "toDate": (end + timedelta(days=1)).isoformat(),   # defensive: toDate may be exclusive
    })
    r.raise_for_status()
    d = r.json()
    bars = []
    for i, ts in enumerate(d["timestamp"]):
        day = datetime.fromtimestamp(ts, IST).date()
        if start <= day <= end:
            bars.append({"date": day, "open": d["open"][i], "high": d["high"][i],
                         "low": d["low"][i], "close": d["close"][i], "volume": d["volume"][i]})
    return bars
```

SDK equivalent: `dhan.historical_daily_data(security_id, exchange_segment, instrument_type, from_date, to_date, expiry_code=0, oi=False)`.

### 7.2 Intraday candles: `POST /v2/charts/intraday`

Body **[SDK]** (adds `interval`, minutes: `1, 5, 15, 25, 60`):

```json
{
  "securityId": "11536", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
  "interval": 5, "oi": false,
  "fromDate": "2026-10-19", "toDate": "2026-10-21"
}
```

Response shape matches daily (arrays; `timestamp` is epoch seconds of candle start). Lookback: the SDK docstring says the **last 5 trading days**; later docs reportedly extended this to ~90 days per request **[UNVERIFIED]**. Some users report `HH:MM:SS` being accepted in `fromDate`/`toDate`. **[UNVERIFIED]**. FinAlly doesn't need intraday history (sparklines are built client-side from the SSE stream), so this is optional.

### 7.3 EOD for many tickers: two strategies

| Strategy | Calls | Notes |
|---|---|---|
| A. `/charts/historical` per ticker | N (≤5/s) | Authoritative; also gives full history |
| B. One `/marketfeed/ohlc` after the close (15:30 IST + margin) | 1 for ≤1000 tickers | Cheap snapshot of today's OHLC; semantics of `close` after the bell must be verified. **[UNVERIFIED]** |

US stocks: no REST history call exists in SDK 2.3.0. Whether `/charts/historical` accepts `exchangeSegment: "INX_EQ"` is **unknown**; treat as unsupported until proven.

---

## 8. Live Market Feed (WebSocket)

Push alternative to polling. Use it if sub-second ticks are needed or for US stocks; otherwise REST polling at 1–2 s is simpler and adequate for FinAlly's 500 ms UI cadence (the cache fan-out already repeats the latest value).

### 8.1 Connection (Indian markets) **[SDK]**

```text
wss://api-feed.dhan.co?version=2&token=<ACCESS_TOKEN>&clientId=<CLIENT_ID>&authType=2
```

Auth is in the query string (the token appears in URLs, so **never log the URL**). The server sends a ping periodically; the `websockets` library answers automatically.

### 8.2 Subscribe / unsubscribe (JSON text frames) **[SDK]**

```json
{
  "RequestCode": 15,
  "InstrumentCount": 2,
  "InstrumentList": [
    {"ExchangeSegment": "NSE_EQ", "SecurityId": "11536"},
    {"ExchangeSegment": "NSE_EQ", "SecurityId": "2885"}
  ]
}
```

| RequestCode | Meaning |
|---|---|
| 15 / 16 | Subscribe / unsubscribe **Ticker** (LTP + last trade time) |
| 17 / 18 | Subscribe / unsubscribe **Quote** (LTP, volume, OHLC, …) |
| 21 / 22 | Subscribe / unsubscribe **Full** (Quote + OI + 5-level depth) |
| 12 | Disconnect |
| 19 | Depth (v1 only; v2 uses 21) |

Max 100 instruments per message; send multiple messages. Unsubscribe = subscribe code + 1 **[SDK]**. Subscribing to Quote/Full also yields extra packets (previous close, OI, market status).

### 8.3 Binary responses (all little-endian) **[SDK]**

Common 8-byte header: `<B H B I` → `response_code` (u8), `message_length` (u16), `exchange_segment` (u8), `security_id` (u32).

| Code | Packet | `struct` format | Size | Fields after header |
|---|---|---|---|---|
| 2 | Ticker | `<BHBIfI` | 16 | `LTP` f32, `LTT` u32 (epoch s) |
| 4 | Quote | `<BHBIfHIfIIIffff` | 50 | LTP f32, LTQ u16, LTT u32, avg_price f32, volume u32, total_sell_qty u32, total_buy_qty u32, open f32, **close f32**, high f32, low f32 |
| 5 | OI | `<BHBII` | 12 | OI u32 |
| 6 | **Previous close** | `<BHBIfI` | 16 | `prev_close` f32, `prev_OI` u32 |
| 7 | Market status | `<BHBI` | 8 | (status only) |
| 8 | Full | `<BHBIfHIfIIIIIIffff100s` | 162 | Quote fields + OI, oi_day_high, oi_day_low, then 5×20-byte depth |
| 50 | Server disconnect | `<BHBIH` | 10 | error code u16 |

The previous-close packet (code 6) is the cleanest source of "previous close" in the live path.

Disconnect error codes (packet 50) **[SDK]**: `805` too many connections, `806` Data APIs not subscribed, `807` token expired, `808` invalid client ID, `809` authentication failed.

Prices are float32, so format to 2 decimals (the SDK does) and round on ingestion; do not compare prices for equality.

### 8.4 Async example: ticker stream with reconnect

```python
import asyncio, json, struct
import websockets

WSS = "wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2"
SEGMENT_NAMES = {0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY",
                 4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO"}

def parse_packet(buf: bytes) -> dict | None:
    code = buf[0]
    if code == 2:                                    # ticker
        _, _, seg, sec, ltp, ltt = struct.unpack("<BHBIfI", buf[:16])
        return {"kind": "ltp", "segment": SEGMENT_NAMES.get(seg), "security_id": sec,
                "price": round(ltp, 2), "ts": ltt}
    if code == 6:                                    # previous close
        _, _, seg, sec, prev, _oi = struct.unpack("<BHBIfI", buf[:16])
        return {"kind": "prev_close", "segment": SEGMENT_NAMES.get(seg),
                "security_id": sec, "prev_close": round(prev, 2)}
    if code == 50:                                   # server-initiated disconnect
        (err,) = struct.unpack("<H", buf[8:10])
        raise ConnectionAbortedError(f"Dhan feed disconnect code {err}")
    return None                                      # other packet types ignored here

async def stream(client_id: str, token: str, instruments: list[tuple[str, int]], on_event):
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(WSS.format(token=token, client_id=client_id)) as ws:
                for i in range(0, len(instruments), 100):
                    batch = instruments[i:i + 100]
                    await ws.send(json.dumps({
                        "RequestCode": 17,          # Quote: also triggers prev-close packets
                        "InstrumentCount": len(batch),
                        "InstrumentList": [{"ExchangeSegment": s, "SecurityId": str(n)}
                                           for s, n in batch],
                    }))
                backoff = 1.0
                async for msg in ws:
                    if isinstance(msg, bytes):
                        ev = parse_packet(msg)
                        if ev:
                            on_event(ev)
        except ConnectionAbortedError:
            raise                                    # auth/subscription problems: don't hot-loop
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
```

Caveats:

- A single WebSocket frame may carry one packet; the Indian feed sends one packet per frame in the SDK's reading loop (`recv()` → `process_data`). **[SDK]**
- Handle `807 token expired` by renewing the token and reconnecting.
- Max 5 connections per user; a restart that overlaps a not-yet-closed socket can trip `805`.

---

## 9. Global Stocks (US) live feed **[SDK]**

```text
wss://global-stocks-api-feed.dhan.co/?clientId=<ID>&token=<TOKEN>&authType=2&version=2
```

`authType`: 1 partner's client, **2 self**, 3 partner. Subscribe (JSON, **lowerCamelCase** keys here, unlike the Indian feed):

```json
{"requestCode": 15, "instrumentCount": 1,
 "instrumentList": [{"exchangeSegment": "INX_EQ", "securityId": "<SCRIP_CODE>"}]}
```

Codes: `15/16` subscribe/unsubscribe **Trade**, `17/18` subscribe/unsubscribe **OHLC**, `12` disconnect.

Packets: 11-byte header `<B i i B B` = `exchange_segment`, `scrip_id`, `scrip_id2`, `msg_length`, `msg_code`. One frame can contain **multiple concatenated packets**; walk it using `msg_length` (the SDK falls back to a per-code size table when it is 0).

| `msg_code` | Packet | Size | Payload (after 11-byte header) |
|---|---|---|---|
| 1 | Trade | 27 | `<fiii` → LTP f32, volume i32, LTT i32, LUT i32 |
| 3 | OHLC | 27 | `<ffff` → open, close, high, low |
| 29 | Market status | 18 | `<3si` → market_type, status |
| 32 | **Previous close** | 15 | `<f` |
| 33 | Circuit limits | 19 | `<ff` |
| 36 | 52-week high/low | 19 | `<ff` |
| 50 | Error | 13 | `<h` → 805–809 (same meanings as above) |

There is a **Global Stocks market status REST call** `GET /v2/globalstocks/marketstatus` **[SDK]**, but no REST quote/history. For US-stock EOD prices, Dhan is not currently a documented source.

---

## 10. Errors

HTTP errors carry a JSON body with `errorCode`, `errorType`, `errorMessage` **[SDK parsing]**.

| Signal | Likely meaning |
|---|---|
| HTTP 401 / `DH-901` | Invalid or expired token / client ID **[UNVERIFIED code]** |
| `DH-902` | No API access / Data API not subscribed **[UNVERIFIED]** |
| HTTP 429 / `DH-904` | Rate limit exceeded (back off) **[UNVERIFIED code]** |
| `DH-905` | Invalid request (bad input) **[UNVERIFIED]** |
| `DH-907` | No data for request (e.g. empty range) **[UNVERIFIED]** |
| Data-API codes `800`-series (804 too many instruments, 806 not subscribed, 807 expired, 808/809 auth, 813 invalid security ID, 814 invalid request) | **[UNVERIFIED]** for REST; 805–809 **[SDK]** for WebSocket |

Client policy: 4xx other than 429 → don't retry (surface error); 429/5xx/timeouts → exponential backoff with jitter; auth errors → mark source unhealthy and stop polling at full speed.

---

## 11. Smoke test (run once with a real account)

This resolves the [UNVERIFIED] items most relevant to FinAlly. Do **not** commit tokens.

```python
# uv run --with httpx python smoke_dhan.py
import json, os, sys
from datetime import date, timedelta
import httpx

cid, tok = os.environ["DHANHQ_CLIENT_ID"], os.environ["DHANHQ_API_KEY"]
h = {"access-token": tok, "client-id": cid, "Content-Type": "application/json"}
base = "https://api.dhan.co/v2"
with httpx.Client(base_url=base, headers=h, timeout=15) as http:
    print("profile:", http.get("/profile", headers={**h, "dhanClientId": cid}).status_code)

    r = http.post("/marketfeed/ohlc", json={"NSE_EQ": [11536]})
    print("ohlc:", r.status_code, json.dumps(r.json(), indent=1)[:600])   # check key names, close semantics

    today = date.today()
    r = http.post("/charts/historical", json={
        "securityId": "11536", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
        "expiryCode": 0, "oi": False,
        "fromDate": (today - timedelta(days=10)).isoformat(), "toDate": today.isoformat()})
    d = r.json()
    print("historical:", r.status_code, {k: (len(v) if isinstance(v, list) else v) for k, v in d.items()})
    print("last bars close:", d.get("close", [])[-3:], "ts:", d.get("timestamp", [])[-3:])
    # Questions answered here: is today's partial candle included? is toDate inclusive?
    # does ohlc.close == previous session close during market hours (compare with last full daily close)?
```

Record the answers in this document and remove the corresponding [UNVERIFIED] tags.

---

## 12. Quick reference

| Need | Call | Cost for N tickers |
|---|---|---|
| Latest price, many tickers | `POST /marketfeed/ltp` | 1 call (≤1000 ids), 1/s |
| Latest + day OHLC | `POST /marketfeed/ohlc` | 1 call |
| Daily candles | `POST /charts/historical` | N calls, 5/s |
| Intraday candles | `POST /charts/intraday` | N calls, 5/s |
| Push ticks (India) | `wss://api-feed.dhan.co?version=2&…` | 1 connection, ≤100 ids/msg |
| Push ticks (US) | `wss://global-stocks-api-feed.dhan.co/?…` | 1 connection |
| Symbol → ID | scrip-master CSV | 1 download/day |
| Token | `GET /v2/RenewToken`, `GET /v2/profile` | 1 per 12–24h |
