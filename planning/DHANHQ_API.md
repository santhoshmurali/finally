# DhanHQ API Reference (for FinAlly market data)

What FinAlly uses from DhanHQ v2: the **Live Market Feed WebSocket** for real-time NSE prices, the **instrument list** for ticker to security ID mapping, and **daily history** over REST. Scope is **Indian markets only** (NSE cash equities, INR). US stocks are out of scope.

Companion docs: [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md) (architecture), [MARKET_INTERFACE.md](MARKET_INTERFACE.md) (the unified Python API), [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the no-token fallback).

Tags: **[VERIFIED]** observed against the live service on 2026-10-22 with a real Data-API-enabled token (market closed, 21:54 to 22:50 IST); **[DOCS]** from the official docs (<https://dhanhq.co/docs/v2/>) or the OpenAPI specs (<https://api.dhan.co/v2/v3/api-docs>); **[UNVERIFIED]** still to be observed during market hours (see section 11).

---

## 1. Credentials

| Item | Value |
|---|---|
| Access token | JWT, 24 h validity **[DOCS]**. Env var `DHAN_ACESS_TOKEN` (the spelling used in the project `.env`; `DHAN_ACCESS_TOKEN` also works). |
| Client ID | Embedded in the token as the `dhanClientId` claim **[VERIFIED]**, so no second variable is needed. `DHAN_CLIENT_ID` can override it. |
| Expiry | The `exp` claim (epoch seconds) **[VERIFIED]**. The backend refuses an expired token at startup and stops the feed when it expires mid-run. |
| Data plan | `GET /v2/profile` returns `dataPlan` (`Active`), `dataValidity`, `tokenValidity` and `activeSegment` **[VERIFIED]**. The live feed and history are Data APIs and need an active plan; without one Dhan answers `806` / `DH-902`. |

Env file note **[VERIFIED]**: the project `.env` wraps the value in double quotes. `python-dotenv` strips them but `docker --env-file` does not, so the backend strips surrounding quotes itself.

Obtaining a token: web.dhan.co, My Profile, *Access DhanHQ APIs* (24 h), or TOTP via `POST https://auth.dhan.co/app/generateAccessToken`, or `GET /v2/RenewToken` for a still-valid web token **[DOCS]**. The backend does not renew tokens; it fails fast and reports unhealthy (runbook in MARKET_DATA_DESIGN.md section 8).

REST headers: `access-token`, `client-id`, `Content-Type: application/json`.

## 2. Hosts, limits, segments

| Purpose | Host |
|---|---|
| REST | `https://api.dhan.co/v2` |
| Live feed | `wss://api-feed.dhan.co` |
| Instrument list | `https://api.dhan.co/v2/instrument/NSE_EQ` (no auth, 302 to a pre-signed S3 URL, follow redirects) |

The sandbox (`https://sandbox.dhan.co/v2`) has trading and chart endpoints only; no quote endpoints and no feed **[DOCS]**, so it cannot back FinAlly prices.

Limits **[DOCS]**: Data APIs (history) 5 requests/s, 100,000/day; Quote APIs 1 request/s; WebSocket 5 connections per user, 5,000 instruments per connection, **100 instruments per subscribe message**.

FinAlly uses a single segment, `NSE_EQ` (numeric code 1 in binary packets). Full segment table: `IDX_I` 0, `NSE_EQ` 1, `NSE_FNO` 2, `NSE_CURRENCY` 3, `BSE_EQ` 4, `MCX_COMM` 5, `BSE_CURRENCY` 7, `BSE_FNO` 8.

## 3. Instrument list (ticker to security ID)

`GET /v2/instrument/NSE_EQ` returns a CSV (~10,000 rows) **[VERIFIED]**. The exchange ticker is `UNDERLYING_SYMBOL`; the security ID is `SECURITY_ID`. The file mixes instrument kinds, so keep only rows with `INSTRUMENT == "EQUITY"` and `SERIES == "EQ"`, which gives unique tickers. Implemented in `app/market/dhan/instruments.py`.

Security IDs of the default watchlist **[VERIFIED]**: RELIANCE 2885, TCS 11536, INFY 1594, HDFCBANK 1333, ICICIBANK 4963, SBIN 3045, BHARTIARTL 10604, ITC 1660, LT 11483, HINDUNILVR 1394. IDs are stable but never hard-coded; the backend downloads the list at startup.

## 4. Live Market Feed (WebSocket)

### 4.1 Connect

```text
wss://api-feed.dhan.co?version=2&token=<TOKEN>&clientId=<CLIENT_ID>&authType=2
```

The token is in the URL, so it must never be logged. The handshake succeeds even with a bad token; the server then drops the connection **without a close frame and without a disconnect packet** (observed in earlier research with an invalid token; not re-run in this session). A client must therefore treat "connected, then closed with no data" as a probable auth problem and back off. The server pings every 10 s; the `websockets` library answers automatically.

### 4.2 Subscribe

JSON text frame, at most 100 instruments per message:

```json
{"RequestCode": 15, "InstrumentCount": 2,
 "InstrumentList": [{"ExchangeSegment": "NSE_EQ", "SecurityId": "11536"},
                    {"ExchangeSegment": "NSE_EQ", "SecurityId": "2885"}]}
```

`15` subscribes the Ticker stream, `16` unsubscribes it. Other codes (`17` Quote, `21` Full, `19` Depth) exist but FinAlly does not use them.

### 4.3 What the server sends **[VERIFIED]**

Right after subscribing, **per instrument, even with the market closed**:

1. a **Ticker** packet (response code 2) with the last traded price, then
2. a **Previous Close** packet (response code 6) with the previous session close.

Then silence until the market trades. During the session Ticker packets follow each price change **[DOCS]**.

Packets are little-endian. Every packet starts with an 8-byte header `<BHBI` (response code u8, message length u16, segment u8, security ID u32):

| Code | Packet | Layout | Bytes | After the header |
|---|---|---|---|---|
| 2 | Ticker | `<BHBIfI` | 16 | LTP f32, last trade time u32 |
| 6 | Previous close | `<BHBIfI` | 16 | previous close f32, previous OI u32 |
| 50 | Disconnect | `<BHBIH` | 10 | error code u16 |
| 4, 5, 8, 3, 1, 7 | Quote, OI, Full, Depth, Index, Status | see **[DOCS]** | | ignored by FinAlly |

Real bytes captured from the feed (TCS, security 11536), used as unit-test fixtures:

```text
Ticker        02100001102d000066ae1c45cc31da6a  ->  price 2506.9
Previous close 06100001102d000000101e4500000000  ->  2529.0
```

Prices are float32; the backend rounds to 2 decimals and never compares for equality.

### 4.4 Findings that shaped the design

| Finding | Evidence | Consequence |
|---|---|---|
| The Previous Close packet is the authoritative previous close | TCS 2529.0 equals the close of the last completed daily bar (2026-10-21) from `/charts/historical` | Day change = price minus this packet's value |
| **The last trade time is IST wall-clock encoded as UTC** | TCS ticker time 1792684492 decodes to `15:54:52 UTC`; the REST quote for the same trade says `22/10/2026 15:54:52` (IST) | The backend ignores the packet timestamp and stamps ticks with receive time |
| Subscribing returns the last tick immediately | Three instruments returned 6 packets inside one second at 21:54 IST | No REST price seeding is needed; the cache fills within a second of start |
| After hours the feed is quiet | No packets for 12 s after the initial burst | Silence is not a failure; only repeated connect failures mark the feed unhealthy |

### 4.5 Disconnect codes

`805` too many connections or requests, `806` Data APIs not subscribed, `807` token expired, `808` authentication failed, `809` token invalid. The backend treats **806 to 809 as fatal** (no retry, source reports unhealthy) and retries anything else with backoff.

## 5. History: `POST /v2/charts/historical`

One instrument per call; request body:

```json
{"securityId": "11536", "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
 "expiryCode": 0, "oi": false, "fromDate": "2026-10-14", "toDate": "2026-10-22"}
```

`toDate` is **non-inclusive**, so the client sends `end + 1 day`. The response is parallel arrays `open, high, low, close, volume, timestamp, open_interest`. `timestamp` is epoch seconds at **IST midnight** of the trading day; convert with a UTC+5:30 zone to get the date. Implemented in `app/market/dhan/client.py`.

Verified behaviour **[VERIFIED]**:

- With `toDate` = tomorrow the response holds **completed sessions only**; the bar for 2026-10-22 was absent at 22:40 IST that day. Days without trading (weekends, 2026-10-20 here) are simply missing.
- An empty range returns **HTTP 400** with `{"errorType":"Data_Error","errorCode":"DH-907",...}`. The client maps `DH-907` to an empty list.

## 6. Quote REST (not used by the backend)

`POST /v2/marketfeed/ltp | ohlc | quote` take `{"NSE_EQ": [11536]}` and are limited to 1 request/s **[DOCS]**. They are documented here only because of what was learned **[VERIFIED]**: after the close, `ohlc.close` equals `last_price` (TCS 2506.9) and `net_change` is 0, so **REST cannot provide the previous close reliably**; the WebSocket Previous Close packet can. A second quote call within one second returned `{"data":{"805":"Too many requests..."},"status":"failed"}`.

## 7. Errors

Two body shapes exist and the client parses both:

1. `{"errorType": "...", "errorCode": "DH-901", "errorMessage": "..."}` (charts and trading APIs, HTTP 4xx/5xx).
2. `{"data": {"808": "Authentication Failed ..."}, "status": "failed"}` (quote APIs and rate limiting).

| Code | Meaning | Mapped to |
|---|---|---|
| `DH-901`, `DH-902`, `806` to `810` | invalid or expired credentials, no Data plan | `AuthenticationError` |
| `DH-904`, `805`, HTTP 429 | rate limited | `RateLimitError` |
| `DH-907` | no data for the parameters | empty result |
| anything else, network errors, malformed bodies | | `DataUnavailableError` |

## 8. Instrument fields and a worked example

```python
# Resolve, then subscribe (the backend does exactly this in DhanDataSource.start)
resolver = await InstrumentResolver.download(httpx.AsyncClient())
security_id = resolver.security_id("TCS")        # 11536
await feed.subscribe([security_id])               # Ticker + Previous Close arrive
```

## 9. Live check performed for this document

Reproducible with the token in `.env` and `backend/`'s code (`DhanDataSource` against the real service):

1. Start with the 10 default tickers. All 10 appeared in the cache with prices and previous closes within seconds (for example TCS 2506.90 vs 2529.00 previous close, -0.87%).
2. `add_ticker("WIPRO")` while connected produced a price (190.41, previous close 189.17) within two seconds.
3. `add_ticker("AAPL")` raised `UnsupportedTickerError` (not an NSE equity).
4. `daily_bars("TCS", ...)` returned the five completed sessions 2026-10-14 to 2026-10-21; the last close matched the feed's previous close.
5. A throwaway uvicorn app serving `GET /api/stream/prices` streamed the same data as SSE.

## 10. Quick reference

| Need | Call |
|---|---|
| Live prices, many tickers | WebSocket, code 15, at most 100 ids per message |
| Previous close | Previous Close packet (code 6), arrives on subscribe |
| Ticker to ID | `GET /v2/instrument/NSE_EQ`, filter `EQUITY` and `EQ` |
| Daily candles | `POST /v2/charts/historical`, one id per call, 5 calls/s |
| Token check | `GET /v2/profile` |

## 11. Not yet verified (needs the market open)

1. Tick cadence and whether every trade produces a Ticker packet.
2. That the server keeps a quiet connection alive past 40 s during the session (the client answers pings, so this is expected).
3. HTTP status code Dhan uses for rate limiting (the body shape is verified).
4. Behaviour when more than one connection is opened with the same token (`805`).
