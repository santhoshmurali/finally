# DhanHQ API Reference (for FinAlly market data)

Research notes on the DhanHQ v2 APIs, scoped to what FinAlly needs: **real-time prices and end-of-day (EOD) prices for multiple tickers**. Order placement, portfolio, funds, option chain, etc. are out of scope.

Companion docs: [MARKET_INTERFACE.md](MARKET_INTERFACE.md) (the unified Python API built on this) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the fallback when no key is set).

---

## 0. Sources and verification status

Researched on **2026-10-22** directly against:

| Source | What it gave us |
|---|---|
| Official docs, <https://dhanhq.co/docs/v2/> (Market Quote, Historical Data, Live Market Feed, Annexure, Authentication, Instrument List, intro/rate-limit pages) | Request/response schemas, limits, error codes, packet layouts |
| Production OpenAPI spec, `https://api.dhan.co/v2/v3/api-docs` (the data behind the Swagger UI at <https://api.dhan.co/v2/#/>) | Which endpoints exist, enums, parameters |
| Sandbox OpenAPI spec, `https://sandbox.dhan.co/v2/v3/api-docs` (UI: <https://sandbox.dhan.co/v2/#/>) | Which endpoints the sandbox offers |
| `dhanhq` Python SDK 2.3.0 source (PyPI) | Global-Stocks (US) feed, binary parsing cross-check |
| Unauthenticated probes of the live hosts (invalid token) | Real error body shapes, sandbox 404 on quote endpoints, segment-wise instrument list |
| Real instrument list `GET /v2/instrument/NSE_EQ` (10,195 rows) | Column names, security IDs for the default watchlist |

Tags used below:

- **[DOCS]**: stated in the official docs pages.
- **[SPEC]**: from the production/sandbox OpenAPI specs.
- **[SDK]**: from the official Python SDK source only.
- **[PROBED]**: observed from a live call made during research (no credentials used).
- **[UNVERIFIED]**: still needs a call with a real, Data-API-subscribed token. These are listed in §12.

> **No authenticated call was made.** Success-path behaviour (actual prices, empty-range handling, `ohlc.close` semantics at specific times) is therefore taken from the docs' examples, not observed.

---

## 1. Scope and the key fit problem

**DhanHQ is an Indian broker API.** Market-data coverage **[DOCS/SPEC]**:

- NSE / BSE equities, indices (`IDX_I`), F&O, currency; MCX commodities, via REST quote/history and the WebSocket feed.
- **US "Global Stocks"** exists in the production spec as `/globalstocks/*`, but only for *trading* (orders, trades, holdings, fund limit, market status, margin/charge estimates). **There is no REST quote or history endpoint for US stocks [SPEC].** A US live feed (`wss://global-stocks-api-feed.dhan.co/`) exists only in the SDK **[SDK]** and is not described in the official docs pages.

FinAlly's default watchlist is US tickers in USD. Consequences:

1. With DhanHQ the natural universe is **NSE equities in INR** (RELIANCE, TCS, INFY, …).
2. US tickers are reachable only through the SDK-documented Global Stocks WebSocket, and there is no documented EOD/history for them.
3. Every ticker must be mapped to a numeric **security ID** via Dhan's instrument list (§5); the quote/history/feed APIs do not accept symbols.

These drive the design choices in MARKET_INTERFACE.md (symbol resolver, `currency`, per-mode default watchlist, capability errors).

---

## 2. Environments, authentication, tokens

### 2.1 Environments

| Environment | REST base | Swagger UI | OpenAPI JSON |
|---|---|---|---|
| Production | `https://api.dhan.co/v2` | <https://api.dhan.co/v2/#/> | `https://api.dhan.co/v2/v3/api-docs` |
| Sandbox | `https://sandbox.dhan.co/v2` | <https://sandbox.dhan.co/v2/#/> | `https://sandbox.dhan.co/v2/v3/api-docs` |
| Auth server | `https://auth.dhan.co` | – | – |
| Live feed (WebSocket) | `wss://api-feed.dhan.co` | – | – |

The Swagger UIs are Stoplight Elements single-page apps that load the OpenAPI JSON above; the JSON is the machine-readable source. **[PROBED]**

### 2.2 Sandbox: what it does and does not offer **[SPEC + PROBED]**

The sandbox spec contains **only trading endpoints plus the two chart endpoints**:

| Capability | Production | Sandbox |
|---|---|---|
| Orders, trades, positions, holdings, forever orders, funds, ledger, kill switch, margin calc, eDIS | ✅ | ✅ (subset) |
| `POST /charts/historical` (daily candles) | ✅ | ✅ |
| `POST /charts/intraday` (minute candles) | ✅ | ✅ |
| **`POST /marketfeed/ltp`, `/ohlc`, `/quote`** | ✅ | ❌ **404** (probed: `{"status":404,"error":"Not Found","path":"/v2/marketfeed/ltp"}`) |
| `/data/*` (technicals, market movers, company info, news) | ✅ | ❌ |
| Super/conditional orders, P&L exit, static-IP setup, `globalstocks/*` | ✅ | ❌ |
| WebSocket live feed | ✅ | not described anywhere; assume ❌ |

**Conclusion: the sandbox cannot supply live quotes, so it cannot back FinAlly's real-time path.** It is usable for exercising authentication and the historical endpoints only; whether its candles are real or synthetic is unknown (**[UNVERIFIED]**, needs a sandbox token; also unknown is whether the sandbox needs a separately issued token; an invalid token returns the same `DH-901` as production).

The production spec does not list `/marketfeed/*` either (it is documented in the docs pages and answers on production; **[PROBED]** returns 401 with an invalid token, not 404), so treat the docs pages, not the spec, as authoritative for quotes.

### 2.3 Credentials and headers

Two credentials are required, not one:

| Credential | Where sent | Notes |
|---|---|---|
| Access token (JWT) | `access-token` header | **24 hours** validity **[DOCS]** |
| Client ID (`dhanClientId`) | `client-id` header | Required by the quote endpoints **[DOCS]**; the chart endpoints document only `access-token` **[DOCS/SPEC]**, but sending both is harmless and what the SDK does |

> The project's `DHANHQ_API_KEY` env var maps to the **access token**; `DHANHQ_CLIENT_ID` is the companion (MARKET_INTERFACE.md §2). (Dhan's own "API key & secret" are a different, OAuth-style credential used to *obtain* tokens; see §2.4.)

```http
access-token: <JWT>
client-id: 1000000001
Content-Type: application/json
Accept: application/json
```

**Data APIs are separately chargeable**: "All Dhan users get access to Trading APIs for free … For Data APIs, there are additional charges which are mentioned on the platform." **[DOCS]** Without the subscription the server answers `DH-902` / `806` (§10). Quotes, history and the live feed are all Data APIs.

### 2.4 Getting and renewing a token **[DOCS]**

| Method | Details |
|---|---|
| **Manual** (simplest) | web.dhan.co → My Profile → *Access DhanHQ APIs* → generate token (24 h). Optional Postback URL. |
| **TOTP** (needs TOTP enabled on the account) | `POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=…&pin=<6-digit PIN>&totp=<code>` → `{"dhanClientId","dhanClientName","dhanClientUcc","givenPowerOfAttorney","accessToken","expiryTime":"2026-…T…"}` (24 h) |
| **API key + secret** (OAuth-like, key valid 12 months) | 1) `POST https://auth.dhan.co/app/generate-consent?client_id={id}` with headers `app_id`, `app_secret` → `consentAppId` (max 25/day). 2) Open `https://auth.dhan.co/login/consentApp-login?consentAppId=…` in a browser, 2FA, get redirected to `{redirect}/?tokenId=…`. 3) `GET https://auth.dhan.co/app/consumeApp-consent?tokenId=…` with `app_id`/`app_secret` headers → `accessToken`, `expiryTime`. |
| **Renew** | `GET https://api.dhan.co/v2/RenewToken` with headers `access-token` and `dhanClientId`. Expires the current token and returns a new 24 h one. **Only for tokens generated from Dhan Web, and only while the token is still active** (renewing an expired token errors). |
| **Validity check** | `GET https://api.dhan.co/v2/profile` with `access-token`, `dhanClientId` **[SDK]** |

Recommendation for FinAlly: read the token from env, validate with `/profile` at startup, treat auth errors as "unhealthy" in `/api/health`, and optionally renew every ~12 h. A fully unattended deployment needs the TOTP route (PIN + TOTP secret), a heavier credential commitment than this project should require by default.

---

## 3. Rate limits and quotas **[DOCS]**

| Bucket | Per second | Per minute | Per hour | Per day |
|---|---|---|---|---|
| Order APIs | 10 | 250 | 1000 | 7000 |
| **Data APIs** (history `/charts/*`, `/data/*`) | **5** | – | – | **100,000** |
| **Quote APIs** (`/marketfeed/*`) | **1** | unlimited | unlimited | unlimited |
| Non-trading APIs | 20 | unlimited | unlimited | unlimited |

Other limits: **1000 instruments per quote request** (code `804` if exceeded); WebSocket: **5 connections per user, 5000 instruments per connection, 100 instruments per subscribe message**; intraday history: **90 days per request**.

---

## 4. Exchange segments and enums

Segment strings (REST bodies, JSON subscribe messages) and numeric codes (binary packet headers) **[DOCS]**:

| String | Code | Exchange / segment |
|---|---|---|
| `IDX_I` | 0 | Index values |
| `NSE_EQ` | 1 | NSE equity cash |
| `NSE_FNO` | 2 | NSE futures & options |
| `NSE_CURRENCY` | 3 | NSE currency |
| `BSE_EQ` | 4 | BSE equity cash |
| `MCX_COMM` | 5 | MCX commodity |
| `BSE_CURRENCY` | 7 | BSE currency |
| `BSE_FNO` | 8 | BSE F&O |

(Code 6 is unassigned.) The **production chart endpoints** accept only `NSE_EQ, NSE_FNO, BSE_EQ, BSE_FNO, MCX_COMM, IDX_I` **[SPEC]**; the sandbox additionally lists `NSE_CURRENCY, BSE_CURRENCY`.

`instrument` values for charts **[DOCS/SPEC]**: `INDEX, FUTIDX, OPTIDX, EQUITY, FUTSTK, OPTSTK, FUTCOM, OPTFUT` (+ `FUTCUR, OPTCUR` in the sandbox spec). Plain stocks use **`EQUITY`**. `expiryCode`: 0 near, 1 next, 2 far (equities: 0).

Feed request codes **[DOCS]**: `11` connect, `12` disconnect, `13/14` unsubscribe/subscribe Index, `15/16` Ticker, `17/18` Quote, `19/20` Market Depth, `21/22` Full, `23/24` Full Market Depth. Feed response codes: `1` Index, `2` Ticker, `3` Market Depth, `4` Quote, `5` OI, `6` Previous Close, `7` Market Status, `8` Full, `50` Disconnect.

---

## 5. Instrument list (symbol → security ID)

Three ways to get the list **[DOCS]**:

| Source | URL | Notes |
|---|---|---|
| **Segment-wise (recommended)** | `GET https://api.dhan.co/v2/instrument/{exchangeSegment}` e.g. `…/instrument/NSE_EQ` | **No auth needed [PROBED]**; answers `302` to a pre-signed S3 URL (`s3.ap-south-1.amazonaws.com`), so the HTTP client **must follow redirects** and the network must allow that host. NSE_EQ is ~1.6 MB / 10,195 rows. |
| Compact (all segments) | `https://images.dhan.co/api-data/api-scrip-master.csv` | Larger; `SEM_*` column names |
| Detailed (all segments) | `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` | Same columns as the segment-wise file |

**Segment-wise / detailed columns [PROBED]** (33): `EXCH_ID, SEGMENT, SECURITY_ID, ISIN, INSTRUMENT, UNDERLYING_SECURITY_ID, UNDERLYING_SYMBOL, SYMBOL_NAME, DISPLAY_NAME, INSTRUMENT_TYPE, SERIES, LOT_SIZE, SM_EXPIRY_DATE, STRIKE_PRICE, OPTION_TYPE, TICK_SIZE, EXPIRY_FLAG, BRACKET_FLAG, COVER_FLAG, ASM_GSM_FLAG, ASM_GSM_CATEGORY, BUY_SELL_INDICATOR, …, MTF_LEVERAGE, SM_UPPER_LIMIT, SM_LOWER_LIMIT, SM_FREEZE_QTY`.
Compact equivalents are `SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID, SEM_INSTRUMENT_NAME, SEM_TRADING_SYMBOL, SEM_CUSTOM_SYMBOL, SEM_SERIES, …` **[DOCS]**.

**The exchange ticker is `UNDERLYING_SYMBOL`** in the segment-wise file (e.g. `M&M`, `ARE&M`); `SYMBOL_NAME` is the legal name and `DISPLAY_NAME` the friendly name. In `NSE_EQ` the file mixes instrument kinds: 10,005 `EQUITY` rows and 190 `INDEX` rows; among equity rows the `SERIES` column includes `EQ` (2,732 rows), `SG`, `N0`, `SM`, `BE`, … (bonds, SME, trade-for-trade). **Filter `INSTRUMENT == "EQUITY"` and `SERIES == "EQ"`: that yields unique `UNDERLYING_SYMBOL`s** (no duplicates **[PROBED]**).

**Security IDs for the proposed default NSE watchlist [PROBED, 2026-10-22]:**

| Ticker | Security ID | Name |
|---|---|---|
| RELIANCE | 2885 | Reliance Industries |
| TCS | 11536 | Tata Consultancy Services |
| INFY | 1594 | Infosys |
| HDFCBANK | 1333 | HDFC Bank |
| ICICIBANK | 4963 | ICICI Bank |
| SBIN | 3045 | State Bank of India |
| BHARTIARTL | 10604 | Bharti Airtel |
| ITC | 1660 | ITC |
| LT | 11483 | Larsen & Toubro |
| HINDUNILVR | 1394 | Hindustan Unilever |

IDs are stable but new listings appear daily; never hard-code, always resolve from the list (cache on disk, refresh daily).

```python
import csv, io
import httpx

def load_nse_equities() -> dict[str, int]:
    """{ticker: security_id} for NSE cash equities in series EQ."""
    r = httpx.get("https://api.dhan.co/v2/instrument/NSE_EQ", timeout=60, follow_redirects=True)
    r.raise_for_status()
    out: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        if row["INSTRUMENT"] == "EQUITY" and row["SERIES"] == "EQ":
            out[row["UNDERLYING_SYMBOL"].strip().upper()] = int(row["SECURITY_ID"])
    return out

ids = load_nse_equities()
assert ids["TCS"] == 11536
```

The US-stock list (SDK only) is `https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv` with columns `EXCHANGE, SEGMENT, SCRIP_CODE, ISIN_CODE, SYMBOL, SYMBOL_NAME, EXCH_SYMBOL, CUSTOM_SYMBOL, TRADING_SYMBOL, …` **[SDK]**; it was not reachable from the research environment, and that `SCRIP_CODE` is the feed's `securityId` is **[UNVERIFIED]**.

---

## 6. Market Quote REST APIs (real-time snapshot, many tickers in one call) **[DOCS]**

Three endpoints, identical request shape:

| Endpoint | Returns |
|---|---|
| `POST /v2/marketfeed/ltp` | Last traded price |
| `POST /v2/marketfeed/ohlc` | LTP + day OHLC |
| `POST /v2/marketfeed/quote` | LTP + OHLC + volume, OI, circuit limits, net change, 5-level depth |

*Limits: up to 1000 instruments per request, 1 request per second.*

**Headers:** `access-token` and `client-id` (both required). **Body:** an object mapping **segment → array of numeric security IDs** (no wrapper):

```json
{ "NSE_EQ": [11536, 2885], "NSE_FNO": [49081] }
```

### Responses

`/marketfeed/ltp`:

```json
{ "data": { "NSE_EQ": { "11536": { "last_price": 4520 } },
            "NSE_FNO": { "49081": { "last_price": 368.15 } } },
  "status": "success" }
```

`/marketfeed/ohlc` (docs example, equity):

```json
{ "data": { "NSE_EQ": { "11536": {
      "last_price": 4525.55,
      "ohlc": { "open": 4521.45, "close": 4507.85, "high": 4530, "low": 4500 } } } },
  "status": "success" }
```

`/marketfeed/quote` fields **[DOCS]**: `average_price` (VWAP), `buy_quantity`, `sell_quantity` (pending at exchange), `depth.buy[5]` / `depth.sell[5]` each `{quantity, orders, price}`, `last_price`, `last_quantity`, `last_trade_time` (string, e.g. `"01/01/1980 00:00:00"` when none), `lower_circuit_limit`, `upper_circuit_limit`, **`net_change` ("absolute change in LTP from previous day closing price")**, `ohlc{open,close,high,low}`, `oi`, `oi_day_high`, `oi_day_low` (F&O), `volume`.

Notes:

- **Security IDs are string keys in the response** (ints in the request). Instruments with no data may be absent or zeroed (the F&O samples show `open/high/low = 0`).
- **`ohlc.close` is described only as "market closing price of the day".** In the equity example `close` (4507.85) differs from `last_price`, which suggests *previous session close during market hours*, but this is **[UNVERIFIED]**. Two better-defined sources of previous close exist: the WebSocket **Previous Close packet** (§8.3) and `/quote`'s **`net_change`** (`previous_close = last_price − net_change`). MARKET_INTERFACE.md derives previous close from daily history (explicit by date) and uses `ohlc.close` only as a last resort.
- Outside market hours LTP is the last traded price; values stop changing.
- **Errors on these endpoints use a different body from the rest of the API [PROBED]**: `{"data": {"808": "Authentication Failed - Client ID or Token invalid"}, "status": "failed"}` with HTTP 401 (code keyed under `data`; see §10).
- The SDK wraps responses as `{"status","remarks","data": <raw JSON>}`, so with the SDK the path is `resp["data"]["data"]["NSE_EQ"]["11536"]["last_price"]`.

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
    flat: dict[str, dict] = {}
    for _segment, by_id in r.json()["data"].items():
        flat.update(by_id)
    return flat

with make_client("1000000001", "eyJ...") as http:
    for sec_id, q in get_ohlc(http, {"NSE_EQ": [11536, 2885]}).items():
        print(sec_id, q["last_price"], q["ohlc"]["close"])
```

### SDK equivalent

```python
from dhanhq import DhanContext, dhanhq

dhan = dhanhq(DhanContext("1000000001", "eyJ..."))
resp = dhan.ohlc_data({"NSE_EQ": [11536, 2885]})   # also ticker_data (LTP) and quote_data
if resp["status"] == "success":
    print(resp["data"]["data"]["NSE_EQ"]["11536"]["last_price"])
else:
    print(resp["remarks"])
```

The SDK is synchronous (`requests`), converts exceptions into `{"status": "failure"}` dicts, and injects `dhanClientId` into every body. For an asyncio FastAPI app prefer a thin httpx client (decision recorded in MARKET_INTERFACE.md §1).

---

## 7. Historical data REST APIs (end-of-day and intraday candles) **[DOCS + SPEC]**

Both are **POST, one instrument per call**; for N tickers make N calls under the 5 req/s Data-API limit. Documented headers: `access-token` (client-id not required, but harmless).

### 7.1 Daily candles: `POST /v2/charts/historical`

*Data is available back to the instrument's inception.*

```json
{
  "securityId": "1333",
  "exchangeSegment": "NSE_EQ",
  "instrument": "EQUITY",
  "expiryCode": 0,
  "oi": false,
  "fromDate": "2022-01-08",
  "toDate": "2022-02-08"
}
```

| Field | Type | Notes |
|---|---|---|
| `securityId` | string, required | |
| `exchangeSegment` | enum, required | §4 |
| `instrument` | enum, required | `EQUITY` for stocks |
| `expiryCode` | int, optional | derivatives only |
| `oi` | bool, optional | open interest |
| `fromDate` | `YYYY-MM-DD`, required | |
| `toDate` | `YYYY-MM-DD`, required | **non-inclusive** (docs) |

Response: **column-oriented arrays** of equal length:

```json
{ "open": [3978, 3856], "high": [3978, 3925], "low": [3861, 3856], "close": [3879.85, 3915.9],
  "volume": [3937092, 1906106], "timestamp": [1326220200, 1326306600], "open_interest": [0, 0] }
```

`timestamp` is **Unix epoch seconds**. Daily candles are stamped at **IST midnight** (1326220200 = 2012-01-10T18:30Z = 2012-01-11 00:00 IST **[verified against the docs example]**), so convert with an IST timezone to get the trading date.

```python
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

def get_daily_bars(http, security_id: int, start: date, end: date,
                   segment="NSE_EQ", instrument="EQUITY") -> list[dict]:
    r = http.post("/charts/historical", json={
        "securityId": str(security_id), "exchangeSegment": segment, "instrument": instrument,
        "expiryCode": 0, "oi": False,
        "fromDate": start.isoformat(),
        "toDate": (end + timedelta(days=1)).isoformat(),   # toDate is non-inclusive
    })
    r.raise_for_status()
    d = r.json()
    return [{"date": day, "open": d["open"][i], "high": d["high"][i], "low": d["low"][i],
             "close": d["close"][i], "volume": d["volume"][i]}
            for i, ts in enumerate(d["timestamp"])
            if start <= (day := datetime.fromtimestamp(ts, IST).date()) <= end]
```

SDK: `dhan.historical_daily_data(security_id, exchange_segment, instrument_type, from_date, to_date, expiry_code=0, oi=False)`.

Whether today's *partial* candle is included when `toDate` is tomorrow is **[UNVERIFIED]**; code that wants "previous close" should filter bars to `date < today` (MARKET_INTERFACE.md does).

### 7.2 Intraday candles: `POST /v2/charts/intraday`

Same body plus `interval` (`"1"|"5"|"15"|"25"|"60"` minutes; the spec types it as a string, the SDK sends an int); `fromDate`/`toDate` accept `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. **Up to 90 days per request; history covers the last 5 years.** Response arrays as above (`timestamp` = candle start epoch). FinAlly doesn't need this (sparklines are built client-side from SSE).

### 7.3 EOD for many tickers: two strategies

| Strategy | Calls | Notes |
|---|---|---|
| A. `/charts/historical` per ticker | N (≤5/s) | Authoritative; also gives full history |
| B. One `/marketfeed/ohlc` (or `/quote`) after the close (15:30 IST + margin) | 1 for ≤1000 tickers | Cheap snapshot; whether `ohlc.close` is today's close after the bell is **[UNVERIFIED]** |

US stocks: no REST history exists **[SPEC]**.

---

## 8. Live Market Feed (WebSocket) **[DOCS]**

Tick-by-tick push; alternative to polling. REST polling at 1–2 s is simpler and adequate for FinAlly's 500 ms UI cadence (the cache fan-out repeats the latest value).

### 8.1 Connection

```text
wss://api-feed.dhan.co?version=2&token=<ACCESS_TOKEN>&clientId=<CLIENT_ID>&authType=2
```

Auth is in the query string (the token appears in the URL, so **never log it**). Authorisation completes asynchronously after connect; failure closes the socket shortly after. **Keep-alive:** the server pings every **10 s**; the client library must answer with a pong (automatic in `websockets`); a client silent for **>40 s** is disconnected.

### 8.2 Subscribe / unsubscribe (JSON text frames)

```json
{ "RequestCode": 15, "InstrumentCount": 2,
  "InstrumentList": [ {"ExchangeSegment": "NSE_EQ", "SecurityId": "1333"},
                      {"ExchangeSegment": "BSE_EQ", "SecurityId": "532540"} ] }
```

Request codes in §4 (15 Ticker, 17 Quote, 21 Full; unsubscribe = code + 1). **≤100 instruments per message**, ≤5000 per connection, ≤5 connections. Subscribing to any packet type also yields a **Previous Close packet**; Quote subscriptions also yield OI packets; a Market Status packet notifies at market open/close.

### 8.3 Binary responses (little-endian)

All responses start with an 8-byte header: `response_code` u8, `message_length` i16, `exchange_segment` u8, `security_id` i32 (`struct` `<BHBI`).

| Code | Packet | `struct` | Bytes | Fields after the header |
|---|---|---|---|---|
| 1 | Index | – | 32 | value f32, day open f32, day close f32 (post-close only), day high f32, day low f32, last update time i32 |
| 2 | **Ticker** | `<BHBIfI` | 16 | LTP f32, LTT i32 (epoch) |
| 3 | Market depth | `<BHBIf100s` | 112 | LTP f32, then 5×20-byte levels `<iihhff` (bid qty, ask qty, bid orders, ask orders, bid price, ask price) |
| 4 | **Quote** | `<BHBIfHIfIIIffff` | 50 | LTP f32, last qty i16, LTT i32, avg price f32, volume i32, total sell qty i32, total buy qty i32, open f32, **close f32 (post-close only)**, high f32, low f32 |
| 5 | OI | `<BHBII` | 12 | OI i32 |
| 6 | **Previous close** | `<BHBIfI` | 16 | previous-day close f32, previous-day OI i32 |
| 7 | Market status | `<BHBI` | 8 | (open/close notification) |
| 8 | Full | `<BHBIfHIfIIIIIIffff100s` | 162 | Quote fields + OI, OI day high/low, + 5-level depth |
| 50 | Server disconnect | `<BHBIH` | 10 | reason u16 (bytes 9–10) |

(Layouts per docs; sizes cross-checked with the SDK parsers. Note: in the Quote packet `close` is documented as "only sent post market close", so use the Previous Close packet for day-over-day comparisons.)

Disconnect reasons: `805` connection limit exceeded, `806` Data APIs not subscribed, `807` token expired, `808` auth failed (check client ID), `809` token invalid.

Prices are float32: round to 2 dp on ingestion, never compare for equality.

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
                        "RequestCode": 15,          # Ticker: LTP + prev-close packet
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

Handle `807` by renewing the token before reconnecting; a restart that overlaps a not-yet-closed socket can trip `805`.

---

## 9. Global Stocks (US) feed **[SDK only]**

Not in the official docs pages; included because FinAlly's default tickers are US stocks.

```text
wss://global-stocks-api-feed.dhan.co/?clientId=<ID>&token=<TOKEN>&authType=2&version=2
```

Subscribe (lowerCamelCase keys): `{"requestCode": 15, "instrumentCount": 1, "instrumentList": [{"exchangeSegment": "INX_EQ", "securityId": "<SCRIP_CODE>"}]}`; codes `15/16` Trade, `17/18` OHLC, `12` disconnect. Packets use an 11-byte header (`<BiiBB`: segment, scrip id, scrip id 2, msg length, msg code); one frame may hold several packets: code 1 Trade (`<fiii`: LTP, volume, LTT, LUT), 3 OHLC (`<ffff`), 32 Previous close (`<f`), 29 market status, 33 circuit limits, 36 52-week range, 50 error (805–809).

REST for US stocks is limited to trading and `GET /v2/globalstocks/marketstatus` **[SPEC]**; no quotes/history. For US-stock EOD prices Dhan is **not** a documented source.

---

## 10. Errors **[DOCS + PROBED]**

Two body shapes exist:

1. **Trading/charts style** (HTTP 4xx/5xx): `{"errorType": "Invalid_Authentication", "errorCode": "DH-901", "errorMessage": "…"}`. **[PROBED]**
2. **Quote style** (`/marketfeed/*`): `{"data": {"808": "Authentication Failed - Client ID or Token invalid"}, "status": "failed"}`, the Data-API numeric code is the key in `data`. **[PROBED]** HTTP 401.

A client must parse **both**.

| Code | Meaning |
|---|---|
| `DH-901` | Client ID or access token invalid/expired |
| `DH-902` | Not subscribed to Data APIs / no access to Trading APIs |
| `DH-903` | Account issue (required segments not activated, …) |
| `DH-904` | Rate limit breached; throttle |
| `DH-905` | Input exception: missing fields, bad values (e.g. *"securityId is required"* **[PROBED]**) |
| `DH-906` | Order error |
| `DH-907` | Data error: incorrect parameters or no data present |
| `DH-908` / `DH-909` / `DH-910` | Internal server / network / other |
| `800` | Internal server error |
| `804` | Requested number of instruments exceeds limit |
| `805` | Too many requests or connections (further requests may get the user blocked) |
| `806` | Data APIs not subscribed |
| `807` | Access token expired |
| `808` | Authentication failed (client ID or token invalid) |
| `809` | Access token invalid |
| `810` | Client ID invalid |
| `811` | Invalid expiry date |
| `812` | Invalid date format |
| `813` | Invalid SecurityId |
| `814` | Invalid request |

Client policy: auth codes (`DH-901`, `DH-902`, `807`–`810`, `806`) → not retryable, mark unhealthy; `DH-904`/`805`/HTTP 429 → exponential backoff; `DH-905`, `804`, `811`–`814` → programming/input error, don't retry; `DH-907` on a history call → treat as "no data" (empty), `DH-908`–`910`/5xx/timeouts → retry with backoff.

---

## 11. Smoke test (run once with a real, Data-API-subscribed token)

Resolves the §12 items. **Do not commit tokens.**

```python
# DHANHQ_CLIENT_ID=... DHANHQ_API_KEY=... uv run --with httpx python smoke_dhan.py
import json, os
from datetime import date, timedelta
import httpx

cid, tok = os.environ["DHANHQ_CLIENT_ID"], os.environ["DHANHQ_API_KEY"]
base = os.environ.get("DHANHQ_BASE_URL", "https://api.dhan.co/v2")
h = {"access-token": tok, "client-id": cid, "Content-Type": "application/json"}
with httpx.Client(base_url=base, headers=h, timeout=15) as http:
    print("profile:", http.get("/profile", headers={**h, "dhanClientId": cid}).status_code)

    for ep in ("ohlc", "quote"):
        r = http.post(f"/marketfeed/{ep}", json={"NSE_EQ": [11536]})
        print(ep, r.status_code, json.dumps(r.json(), indent=1)[:900])
        # Check: ohlc.close vs previous session close; net_change populated for NSE_EQ?

    today = date.today()
    r = http.post("/charts/historical", json={
        "securityId": "11536", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
        "expiryCode": 0, "oi": False,
        "fromDate": (today - timedelta(days=10)).isoformat(),
        "toDate": (today + timedelta(days=1)).isoformat()})
    d = r.json()
    print("historical:", r.status_code, {k: (len(v) if isinstance(v, list) else v) for k, v in d.items()})
    print("last closes:", d.get("close", [])[-3:], "ts:", d.get("timestamp", [])[-3:])
    # Check: is today's partial candle included when toDate=tomorrow (during/after the session)?
```

Run it against production, and (optionally) against the sandbox with `DHANHQ_BASE_URL=https://sandbox.dhan.co/v2`: expect `/marketfeed/*` to 404 there (§2.2) and see whether `/charts/historical` returns real-looking candles.

---

## 12. Still unverified (needs an authenticated call)

1. `ohlc.close` semantics during the session vs. after the close; whether `/quote`'s `net_change` is populated for `NSE_EQ` (would give `previous_close = last_price − net_change` in the same call).
2. Whether today's partial daily candle is returned when `toDate` is tomorrow.
3. Behaviour for empty ranges / holidays (`DH-907` vs empty arrays) and for instruments missing from a quote request (omitted vs zeroed).
4. HTTP status used for rate limiting (429 vs 400 + `DH-904`/`805`).
5. Sandbox: token source, and whether its candles are real or synthetic.
6. US feed: `SCRIP_CODE` as `securityId`, account eligibility, and availability of any EOD source.
7. Exact Data-API subscription price/terms ("mentioned on the platform").

---

## 13. Quick reference

| Need | Call | Cost for N tickers |
|---|---|---|
| Latest price, many tickers | `POST /marketfeed/ltp` | 1 call (≤1000 ids), 1/s |
| Latest + day OHLC | `POST /marketfeed/ohlc` | 1 call |
| Latest + net change + depth | `POST /marketfeed/quote` | 1 call |
| Daily candles | `POST /charts/historical` | N calls, 5/s, 100k/day |
| Intraday candles | `POST /charts/intraday` | N calls, 90-day window |
| Push ticks (India) | `wss://api-feed.dhan.co?version=2&…` | 1 connection, ≤100 ids/msg |
| Symbol → ID | `GET /v2/instrument/NSE_EQ` (follow redirect, no auth) | 1 download/day |
| Token | `GET /v2/RenewToken`, `GET /v2/profile`, `auth.dhan.co/app/generateAccessToken` | 1 per 12–24 h |
