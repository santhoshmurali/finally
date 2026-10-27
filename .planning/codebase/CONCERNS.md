---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# Codebase Concerns

**Analysis Date:** 2026-10-27

## Scope Summary

Only the market data layer (`backend/app/market/`), the console demo (`backend/demo/`), and their tests exist. Per `planning/PLAN.md` §13, the database, portfolio/trade API, watchlist API, LLM chat, FastAPI app wiring, `/api/health`, frontend, Dockerfile, start/stop scripts, and Playwright E2E tests are **not started**. Most concerns below are about the built part; the missing part is listed under "Missing Critical Features".

## Secrets and Credential Handling

**Secret scan of tracked files:**
- A pattern scan (API-key, JWT, AWS key, private-key header, and `key/token/secret/password = value` shapes) over all tracked files, including `.claude/`, `.github/`, `Docs/`, `planning/`, and `backend/`, found no hits. No secret values were recorded in this document.
- Git history: the only env-template file ever committed is `.env.example`. A real `.env` has never been committed.
- A local `.env` file exists at the project root. It is gitignored (`.gitignore` line 138). Its contents were not read for this analysis.

**Concerns:**
- Risk: `.gitignore` only ignores the exact name `.env` (plus `.envrc`). Files such as `.env.local` or `.env.production` would be committed by `git add`, and the Dhan token and `OPENROUTER_API_KEY` would be exposed with them.
  - Files: `.gitignore` (lines 137-139)
  - Current mitigation: none beyond the exact `.env` rule.
  - Recommendation: add `.env.*` and then `!.env.example` to `.gitignore`.
- Risk: the Dhan access token is sent in the WebSocket URL query string, because Dhan's feed API requires it there.
  - Files: `backend/app/market/dhan/feed.py` (`FEED_URL`, line 23; URL built in `_stream_once`, line 98)
  - Current mitigation: `feed.py` lines 20-21 pin the `websockets` logger to INFO so the URL is not logged at DEBUG. Log lines in `feed.py` log only exception type names. `Credentials.__repr__` in `backend/app/market/dhan/auth.py` hides the token.
  - Recommendations: never log the raw URL or the exception `repr` of a handshake failure. Scrub the URL if a traceback is ever printed. The unhandled exception path (anything other than `WebSocketException` or `OSError`) can surface the URL in a traceback.
- Risk: the JWT is decoded without signature verification, and its `exp` claim is trusted for the local expiry check.
  - Files: `backend/app/market/dhan/auth.py` (`credentials_from_token`, lines 40-54)
  - Current mitigation: Dhan validates the token server-side, and the local check only decides when to stop early. Low impact.
- Risk: the token value is read from the environment and passed to `Credentials`. Quote-stripping is needed because `docker --env-file` keeps quotes.
  - Files: `backend/app/market/dhan/auth.py` (`token_from_env`, lines 27-37)
  - Current mitigation: quotes are stripped, and `DHAN_ACESS_TOKEN` (the spelling used in `planning/PLAN.md` §5 and `Docs/help.md`) and `DHAN_ACCESS_TOKEN` are both accepted. The misspelling is a documentation hazard: new docs or `.env.example` entries that use the correct spelling alone would silently fall back to the simulator if the code did not accept both. Keep both names accepted, and pick one in the next doc revision.

## Tech Debt

**Missing production artifacts, but the README advertises them:**
- Issue: `README.md` documents `docker build -t finally .` and `docker run ... finally`, but no `Dockerfile` exists. Likewise no `docker-compose.yml`, `scripts/`, or `test/` directory exists.
  - Files: `README.md` (lines 33-35), `planning/PLAN.md` §11
  - Impact: a new user following the README gets a build error. The "single command" promise in PLAN §2 is not met.
  - Fix approach: either mark the Docker section "planned" until the Dockerfile lands, or add the Dockerfile in the next phase. When it is added, install with `uv sync --no-default-groups` (or `--no-dev --no-group demo`). `backend/pyproject.toml` sets `[tool.uv] default-groups = ["dev", "demo"]`, so a plain `uv sync` would include `prompt-toolkit` and `pytest`, which PLAN §13 says must stay out of the production image.

**Broken documentation links:**
- Issue: `planning/PLAN.md` §6 links `MARKET_DATA_DESIGN.md`, `MARKET_INTERFACE.md`, `DHANHQ_API.md`, and `MARKET_SIMULATOR.md` relative to `planning/`, but those files live in `planning/archive/`. `README.md` has the same kind of cross-reference.
  - Files: `planning/PLAN.md` (§6, line ~163), `planning/archive/*.md`
  - Impact: agents that follow PLAN.md links (the stated shared contract) hit 404s and may guess at the design instead of reading it.
  - Fix approach: update the link targets to `archive/...`, or move the docs back, and keep one path.

**Hard-coded market-data assumptions:**
- Issue: the instrument master CSV is downloaded from Dhan on every startup, with no local cache.
  - Files: `backend/app/market/dhan/instruments.py` (`NSE_EQUITY_URL`, line 12; `download`, lines 32-40), called from `backend/app/market/dhan/source.py` (`start`, line 47-48)
  - Impact: startup fails with `DataUnavailableError` if Dhan's instrument endpoint is down, even though the price feed itself may be fine. The download is large and has a 60-second timeout.
  - Fix approach: cache the parsed CSV to a local file with a daily expiry and fall back to it on failure. Keep it simple: one JSON file is enough.

- Issue: `DhanDataSource.start` builds the resolver from a fresh `httpx.AsyncClient`, while the REST client is a separate long-lived client created in `__init__`. Two HTTP clients exist for one Dhan source.
  - Files: `backend/app/market/dhan/source.py` (lines 39, 47-48), `backend/app/market/dhan/client.py` (line 38)
  - Impact: small. It adds a bit of connection overhead and makes it harder to inject one fake in tests.

**Mixed concurrency primitives in the price cache:**
- Issue: `PriceCache` uses a `threading.Lock` in an asyncio-only program. The `version` property is read without the lock.
  - Files: `backend/app/market/cache.py` (lines 16-23, 33, 48, 66, 71)
  - Impact: harmless in the current single-loop design, but misleading. If a future background thread writes to the cache, `version` can be read out of step with the data.
  - Fix approach: keep the lock if any thread writes (the demo or a sync caller could), and document that the cache is single-loop. Do not add more locking than needed.

**Silent dropping of duplicate instrument symbols:**
- Issue: `InstrumentResolver.from_csv` keeps the last row when two EQ rows share one `UNDERLYING_SYMBOL`.
  - Files: `backend/app/market/dhan/instruments.py` (`from_csv`, lines 24-30, `_add` lines 42-44)
  - Impact: a ticker could resolve to the wrong security ID without any error. Unlikely for NSE EQ, but silent.
  - Fix approach: log or count duplicates during the load.

**Ticker registry mutated before subscription succeeds:**
- Issue: `DhanDataSource.add_ticker` adds the ticker to `self._tickers` before `self._feed.subscribe(...)` runs. If `subscribe` raises, the in-memory set says "subscribed" while the feed is not.
  - Files: `backend/app/market/dhan/source.py` (`add_ticker`, lines 62-68)
  - Impact: the ticker's prices are never delivered until a restart, and the caller gets an exception after the state has already changed.
  - Fix approach: subscribe first, then add to the set. `subscribe` is unlikely to fail for an already-validated security ID, so this is low priority.

## Known Bugs and Behavioural Gaps

**Rejected WebSocket handshake is treated as a transient error, not as an auth failure:**
- Symptoms: when Dhan rejects the handshake with HTTP 401/403 (for example, a token revoked before its expiry time), the feed does not stop. It retries with backoff, and only marks itself unhealthy after 3 failures.
- Files: `backend/app/market/dhan/feed.py` (`_stream_once`, lines 100-111; `_handle`, lines 124-129), `backend/app/market/dhan/source.py` (`healthy`, lines 85-87)
- Trigger: a revoked or otherwise rejected token. The clock-based expiry check in `run()` (lines 80-82) catches only tokens that have expired by the local clock.
- Mismatch: `planning/PLAN.md` §6 says "an authentication failure stops retrying and marks the source unhealthy". Only the in-band `Disconnect` codes 806-809 do that. A handshake `InvalidStatus` (a `WebSocketException` subclass) falls into the generic reconnect path.
- Workaround: restart the app with a new token. Do not rely on automatic retry stopping.
- Fix approach: catch the handshake rejection (`websockets.InvalidStatus` with status 401 or 403) in `_stream_once` and set `self.error = AuthenticationError(...)`, then exit `run()`. Add a fake-socket test in `backend/tests/market/test_dhan_feed.py`.

**Expired token at startup vs. mid-session:**
- Symptoms: an expired token stops startup with `AuthenticationError` (`auth.py` line 53), which is the intended behaviour. A token that expires during a run makes `run()` set `error` (`feed.py` line 81), and `/api/health` will report unhealthy, but nothing restarts the process or notifies the UI.
- Files: `backend/app/market/dhan/feed.py` (lines 80-82), `backend/app/market/dhan/source.py` (`healthy`)
- Trigger: a long session that crosses the 24-hour token lifetime. PLAN §13 notes this is unobserved for full sessions.
- Workaround: restart the app with a new token.

**Simulator and synthetic history use the host's local date:**
- Symptoms: `synthetic_history.py` anchors on `date.today()`, which is the host's local date. In the Docker container (UTC) this differs from an IST host near midnight. The simulator also has no market calendar, so it generates "trading" ticks on weekends and NSE holidays (PLAN §13 known limit).
- Files: `backend/app/market/synthetic_history.py` (line 23), `backend/app/market/simulator.py`
- Trigger: running the demo or app on a weekend, on an NSE holiday, or within a few hours of midnight IST on a non-UTC host.
- Fix approach: anchor to `datetime.now(IST).date()` using the IST zone already defined in `backend/app/market/dhan/client.py` (line 22). Move the IST constant to a shared module. Adding a market calendar is a separate, larger item.

**Demo exits without stopping the source on a failed start:**
- Symptoms: in `amain`, the `try/finally` that calls `source.stop()` wraps only `run_tui`/`run_plain`. If `demo.start` raises after partially starting the source, the source is not stopped.
- Files: `backend/demo/live_console.py` (`amain`, lines 216-240)
- Impact: low. The process exits right after, so there is no lasting leak, but it is an inconsistent cleanup pattern.
- Fix approach: move `source.stop()` into a `finally` that covers `demo.start` too, and make `stop()` safe to call on a source that never started.

**SSE sends every price on every change:**
- Symptoms: `price_events` builds and sends a snapshot of all tickers whenever the global cache `version` changes, and the version bumps on any single ticker's update. With N tickers ticking, the stream sends the full set roughly once per 0.5 s per client.
- Files: `backend/app/market/stream.py` (lines 33-42)
- Impact: fine for 10 tickers and one browser. Bandwidth and JSON encoding grow with the watchlist size and client count, and JSON is encoded separately for each connected client.
- Fix approach: keep it as is for now. If watchlists grow, encode once per version and share the bytes across clients, or send per-ticker deltas.

## Security Considerations

**No authentication, and the README publishes the port on all interfaces:**
- Risk: once the API exists, any host that can reach port 8000 can read the portfolio, execute trades, and spend LLM credits through the chat endpoint. The README command `docker run -p 8000:8000` binds to all host interfaces by default.
- Files: `README.md` (line 35)
- Current mitigation: none (no auth planned; PLAN §2 says "No login, no signup").
- Recommendations: publish the port on loopback only (`-p 127.0.0.1:8000:8000`) in the Dockerfile docs and in `scripts/start_*`. Document that the app is single-user and local-only.

**LLM output drives trade execution with no confirmation:**
- Risk: the LLM chooses tickers and quantities that are executed automatically (PLAN §9). Chat input and any text echoed back into the prompt can steer the model (prompt injection), and malformed structured output could produce unintended trades.
- Files: not built yet. Relevant spec: `planning/PLAN.md` §9.
- Current mitigation: PLAN §9 requires the same validation as manual trades (cash, shares). Nothing is implemented yet.
- Recommendations: validate every LLM-proposed ticker against the NSE resolver (`UnsupportedTickerError`), cap quantity per trade and per reply, reject unknown fields in the structured output, and never call the trade path from free text.

**Public GitHub automation trigger:**
- Risk: `.github/workflows/claude.yml` runs `anthropics/claude-code-action` on any `issue_comment`, `issues`, or review comment that contains `@claude`. It uses the `CLAUDE_CODE_OAUTH_TOKEN` secret (by name only; no value in the repo).
- Files: `.github/workflows/claude.yml`
- Current mitigation: `permissions` are read-only for contents and PRs, and the action applies its own actor-permission checks. Whether the repository is public and who can comment was not verified.
- Recommendations: confirm the repository's visibility and collaborator permissions, and restrict the trigger if outside users can open issues.

## Performance Bottlenecks

**Startup download of the full NSE instrument list:**
- Problem: every start downloads and parses the complete NSE_EQ CSV before any price streams.
- Files: `backend/app/market/dhan/instruments.py` (lines 32-40)
- Cause: no cache (see Tech Debt).
- Improvement path: cache to disk with a daily refresh, as described above.

**Shared rate-limit gap serialises REST calls:**
- Problem: `DhanClient._throttle` holds an `asyncio.Lock` while sleeping up to 0.2 s, so all history requests run one at a time.
- Files: `backend/app/market/dhan/client.py` (lines 83-88)
- Cause: the design matches Dhan's 5 requests per second limit, which is intentional.
- Improvement path: none needed for watchlist-sized requests. Note it when batch history loading is added.

## Fragile Areas

**Dhan feed reconnect and health state machine:**
- Files: `backend/app/market/dhan/feed.py` (`run`, `_stream_once`, `_handle`, `subscribe`, `unsubscribe`, `_send`)
- Why fragile: three flags (`_received`, `_failures`, `error`) and the `_ws` handle are updated across async tasks. `_send` silently ignores `ConnectionClosed` and relies on resubscription on the next connect. A subscribe call made during reconnect can be lost if the socket closes between the `_ws` check and the send.
- Safe modification: change one behaviour at a time, and keep the fake socket in `backend/tests/market/dhan_fakes.py` as the test harness. Every change to `_handle` needs a test for the disconnect path.
- Test coverage: the fake-socket tests exist in `backend/tests/market/test_dhan_feed.py`. The handshake-rejection path (see Known Bugs) is not covered.

**Binary packet parsing without length validation:**
- Files: `backend/app/market/dhan/packets.py` (`parse_packet`, lines 50-66)
- Why fragile: `struct.unpack` is applied to `buf[:16]` and `buf[:10]` with no check that the buffer is long enough. Short packets raise `struct.error`, which the feed catches (`feed.py` line 121) and logs, so the failure is contained.
- Safe modification: keep the `struct.error` catch in `feed.py`, and add a test for truncated packets in `backend/tests/market/test_dhan_packets.py`.

**Global module-level state in the demo:**
- Files: `backend/demo/live_console.py` (`Demo`, lines 77-96)
- Why fragile: the `Demo` object owns the watchlist, the chart buffers, and the source. Its `symbols` list is set only after `source.start` returns (line 92), so a failed start leaves it empty.
- Safe modification: keep state updates after successful calls, and test the full-screen path only through the typed-input tests described in PLAN §13.

## Scaling Limits

**Single in-process price cache and one SSE loop:**
- Current capacity: one process, one cache, and one watchlist. Verified with 10 default tickers and a 6-minute market-hours run (PLAN §13).
- Limit: the cache is a single dict in one process. The design explicitly targets one user, so this is not a near-term problem. Multi-process uvicorn workers would each run their own feed and would open multiple Dhan WebSocket connections, which Dhan's limits may not allow.
- Scaling path: run one worker. Keep the single-worker constraint in the Dockerfile and `uvicorn` command when it is written.

**Dhan subscription batches:**
- Current capacity: `MAX_INSTRUMENTS_PER_MESSAGE = 100` in `feed.py` (line 26), with a batched send. Current usage is about 10 to 15 instruments.
- Limit: Dhan's per-connection instrument limit is not stated in the repo. Unverified.
- Scaling path: check Dhan's documented per-connection limit before allowing large watchlists.

## Dependencies at Risk

**Dhan feed and history APIs (external contract):**
- Risk: the feed URL (`wss://api-feed.dhan.co?version=2...`), the request codes (`SUBSCRIBE_TICKER = 15`, `UNSUBSCRIBE_TICKER = 16`), the error code sets in `client.py` (lines 25-27), and the packet layouts in `packets.py` are hard-coded against the DhanHQ v2 API as observed on 2026-10-26.
- Impact: any Dhan change breaks the live path silently or with unclear errors.
- Migration plan: keep the constants in one place (already true for most), and keep the archived `planning/archive/DHANHQ_API.md` current with the observed behaviour.

**Python version drift:**
- Risk: `backend/pyproject.toml` requires Python `>=3.12`, but local bytecode caches are `cpython-314`, and `client.py` imports `datetime.UTC` (Python 3.11+). Dockerfile (not written) plans Python 3.12.
- Impact: low today. Mismatch could hide 3.13/3.14-only behaviour.
- Migration plan: pin the Dockerfile base to the same minor version as the lockfile and run the test suite on that version.

## Missing Critical Features

**Everything outside the market data layer (per `planning/PLAN.md` §13):**
- Problem: no database (`backend/db/` missing), no portfolio or trade API, no watchlist API, no snapshots task, no `/api/health`, no FastAPI app (`backend/app/main.py` missing), no LLM integration or mock mode, no frontend, no Dockerfile, no start/stop scripts, no Playwright tests.
- Blocks: the core user flow in PLAN §2 (trading, P&L, chat). Nothing in the repo can yet run the product end to end.
- Priority: High. The next phases should be: database and lazy init, FastAPI wiring with the existing `create_stream_router`, trade and portfolio API, then `/api/health` reporting `source.healthy()`.

## Test Coverage Gaps

**Backend API, database, and LLM layers have no tests because they do not exist:**
- What's not tested: everything listed under Missing Critical Features.
- Files: `backend/tests/` covers `market/` and `demo/` only.
- Risk: when the API lands, the trade-validation rules (cash, shares, unsupported ticker) have no existing test harness.
- Priority: High once the portfolio code exists.

**Handshake-rejection and token-revocation paths in the Dhan feed:**
- What's not tested: a rejected WebSocket handshake (HTTP 401/403) and a token revoked before its expiry time.
- Files: `backend/app/market/dhan/feed.py`, `backend/tests/market/test_dhan_feed.py`
- Risk: the feed keeps retrying a dead token without surfacing an auth error (see Known Bugs).
- Priority: High. This directly affects the "expired token stops startup" contract in PLAN §5.

**Simulator behaviour on non-trading days:**
- What's not tested: weekend and holiday behaviour, and the midnight/timezone boundary in `synthetic_history.py`.
- Files: `backend/app/market/synthetic_history.py`, `backend/tests/market/test_synthetic_history.py`
- Risk: flaky or wrong anchor dates depending on the host's timezone.
- Priority: Low.

**Startup failure paths in the console demo:**
- What's not tested: a failed `demo.start` followed by `source.stop()` (see Known Bugs).
- Files: `backend/demo/live_console.py`, `backend/tests/demo/test_console.py`
- Risk: low; the process exits immediately.
- Priority: Low.

---

*Concerns audit: 2026-10-27*
