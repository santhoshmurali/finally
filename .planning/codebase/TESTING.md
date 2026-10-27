---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# Testing Patterns

**Analysis Date:** 2026-10-27

## Test Framework

**Runner:**
- pytest 9.x (dev dependency, `backend/pyproject.toml` `[dependency-groups] dev`)
- pytest-asyncio 1.x, in `asyncio_mode = "auto"`
- pytest-cov 7.x for coverage
- Config: `backend/pyproject.toml` under `[tool.pytest.ini_options]`:
  ```toml
  asyncio_mode = "auto"
  testpaths = ["tests"]
  ```

**Assertion Library:**
- Plain `assert` statements (pytest rewriting).
- `pytest.approx` for floating-point and statistical tolerances (`backend/tests/market/test_simulator.py`).

**Lint:**
- Ruff runs over tests as well as app code (`uv run ruff check app tests` per `Docs/help.md`; `uv run ruff check .` passes on the whole backend).

**Run Commands** (all from `backend/`):
```bash
uv run pytest                  # Run all tests (163 at last count: 125 market data + 38 demo)
uv run pytest tests/market     # Market data only
uv run pytest tests/demo       # Console demo only
uv run pytest --cov=app        # Coverage of app/ (reported 100% line coverage in PLAN.md §13)
uv run ruff check app tests    # Lint
```
- No watch mode is configured. Use `uv run pytest -x -q` for fast iteration.
- The `demo` dependency group (prompt-toolkit) is in `default-groups` (`[tool.uv] default-groups = ["dev", "demo"]`), so `uv run pytest` includes the demo tests. The production image must be built without the `dev` and `demo` groups (PLAN.md §13).
- Coverage numbers were not re-measured for this analysis; the 100% figure is the team's reported value.

## Test File Organization

**Location:**
- Separate tree, not co-located: all tests live under `backend/tests/`, mirroring the package layout.
- `backend/tests/market/` covers `backend/app/market/`.
- `backend/tests/demo/` covers `backend/demo/`.
- Every test directory is a package with an empty-or-docstring `__init__.py` (`backend/tests/__init__.py`, `backend/tests/market/__init__.py`, `backend/tests/demo/__init__.py`). This lets helpers be imported relatively.

**Naming:**
- Files: `test_<module or concern>.py`. Examples: `test_simulator.py`, `test_dhan_auth.py`, `test_dhan_feed.py`, `test_factory_stream.py`, `test_models_cache.py`.
- The Dhan tests are split per component: `test_dhan_auth.py`, `test_dhan_client.py`, `test_dhan_feed.py`, `test_dhan_instruments.py`, `test_dhan_packets.py`, `test_dhan_source.py`.
- Functions: `test_<behaviour in words>`, e.g. `test_same_seed_gives_same_path`, `test_events_produce_2_to_5_percent_jumps`, `test_add_and_remove_tickers`.
- Each module starts with a one-line docstring naming what it covers, e.g. `"""GBMSimulator maths and SimulatorDataSource behaviour."""`.

**Helper modules:**
- Shared fakes live in non-test-prefixed modules, imported relatively: `from .dhan_fakes import FakeConnect, disconnect_bytes, prev_close_bytes, ticker_bytes` (`backend/tests/market/test_dhan_source.py`).

**Structure:**
```
backend/tests/
├── __init__.py
├── demo/
│   ├── __init__.py
│   ├── test_console.py
│   └── test_render.py
└── market/
    ├── __init__.py
    ├── dhan_fakes.py        # Fake WebSocket, packet bytes
    ├── test_dhan_auth.py
    ├── test_dhan_client.py
    ├── test_dhan_feed.py
    ├── test_dhan_instruments.py
    ├── test_dhan_packets.py
    ├── test_dhan_source.py
    ├── test_factory_stream.py
    ├── test_models_cache.py
    ├── test_simulator.py
    └── test_synthetic_history.py
```
There is no `conftest.py` today. Fixtures are defined in the test module that uses them.

## Test Structure

**Suite organization:** flat module-level functions. No test classes were found in the suite. Group related tests by module, not by class.

```python
def test_starts_at_seed_prices():
    sim = GBMSimulator(DEFAULT_WATCHLIST, seed=1)
    assert sim.step().keys() == set(DEFAULT_WATCHLIST)
    assert sim.add_ticker("TCS") == pytest.approx(SEED_PRICES["TCS"], rel=0.01)
```

**Async tests:** write them as `async def test_...` with no marker. `asyncio_mode = "auto"` runs them on an event loop automatically.

```python
async def test_live_packets_fill_the_cache(parts):
    cache = parts[0]
    ...
```

**Fixtures:**
- Defined with `@pytest.fixture` in the same module. Sync fixtures return values; async fixtures use `yield` and clean up after the yield.
- Example async fixture that stops the source on teardown (`backend/tests/demo/test_console.py`):
```python
@pytest.fixture
async def demo():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=0.01, seed=1)
    demo = Demo(source, cache, window=10, interval=0.02)
    await demo.start(["TCS", "ITC"])
    yield demo
    await source.stop()
```
- Composite fixtures return tuples (`parts` returns `(cache, client, resolver)` in `backend/tests/market/test_dhan_source.py`) and are unpacked by the test or a `build(parts, *sessions)` helper.

**Patterns:**
- Setup: construct real objects with small inputs and fixed seeds. Only external I/O is faked.
- Teardown: `yield`-style fixtures, or `await source.stop()` at the end of a test.
- Assertion: direct `assert`. Compare tuples for multi-field checks: `assert (up.direction, up.change) == ("up", 1.0)`.
- Parametrisation: not used so far. Write one test per case when needed, or loop inside the test.

## Waiting for Async State

Background tasks are polled rather than slept on. The helper in `backend/tests/market/test_dhan_source.py` yields to the loop until a condition holds:
```python
async def until(condition, tries=200):
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")
```
Prefer this over fixed `asyncio.sleep(1)`. Use `asyncio.sleep(0)` for yielding, and small real intervals only where the test measures streaming (`update_interval=0.01` in the demo fixture).

## Mocking and Fakes

**Framework:** no `unittest.mock`, `MagicMock`, or `patch` in the suite. The team uses hand-written fakes and `httpx.MockTransport`.

**Fake WebSocket** (`backend/tests/market/dhan_fakes.py`): `FakeConnection` is an async context manager that replays a script. Items are bytes (delivered as messages), exceptions (raised), or callables (invoked, e.g. `feed.stop`). It records what the client sent in `self.sent`.

**Fake HTTP:** `httpx.MockTransport` with a handler function:
```python
transport = httpx.MockTransport(lambda request: httpx.Response(500))
async with httpx.AsyncClient(transport=transport) as http:
    ...
```
(`backend/tests/market/test_dhan_instruments.py`, `test_dhan_client.py`)

**Fake collaborator classes:** small classes with the same method names as the real one, recording calls. `FakeClient` in `backend/tests/market/test_dhan_source.py` records `daily_bars` calls and tracks `closed`.

**Injection, not patching:** pass fakes through constructor keyword arguments:
```python
source = DhanDataSource(cache, CREDENTIALS, resolver=resolver, client=client)
source._feed = DhanFeed(CREDENTIALS, source._on_packet, connect=connect)
```
Setting `source._feed` after construction reaches into a private attribute. Acceptable in tests, but prefer the constructor keyword (`feed=`) when adding new tests.

**Environment:** pass an explicit mapping instead of touching `os.environ`:
```python
create_market_source(cache, env={"DHAN_ACESS_TOKEN": make_token(exp)})
```
(`backend/tests/market/test_factory_stream.py`)

**Module constants:** `monkeypatch.setattr` is the standard way to override a module constant:
```python
def test_events_produce_2_to_5_percent_jumps(monkeypatch):
    monkeypatch.setattr(simulator_module, "EVENT_PROBABILITY", 1.0)
```
Note: `backend/tests/market/test_simulator.py` also swaps `EVENT_PROBABILITY` by hand with `try/finally` in two statistical tests. Prefer `monkeypatch` for new tests; it restores automatically.

**What to Mock:**
- Network: Dhan WebSocket (use `FakeConnect`), Dhan REST (use `httpx.MockTransport`).
- Time-dependent provider replies that are scripted (feed disconnect codes, auth failures).
- Credentials and environment mappings.
- Module constants that control randomness or probability of rare events.

**What NOT to Mock:**
- The `PriceCache`, `PriceUpdate`, and `GBMSimulator`. Use the real objects; they are fast and pure.
- Packet decoding. Build real bytes with `struct.pack` helpers (`ticker_bytes`, `prev_close_bytes`, `disconnect_bytes` in `dhan_fakes.py`) and decode them for real.
- The seed price table. Tests read `SEED_PRICES` and `DEFAULT_WATCHLIST` directly.

## Determinism and Randomness

- Seed every simulator: `GBMSimulator(tickers, seed=1)`, `SimulatorDataSource(cache, seed=1)`. Same seed must give the same path (`test_same_seed_gives_same_path`).
- Statistical tests are allowed, with explicit tolerances and large samples, and they turn off random events to isolate the effect under test:
```python
assert returns.std() == pytest.approx(0.19 * np.sqrt(1e-5), rel=0.08)
assert same_group == pytest.approx(0.6, abs=0.06)
```
- Use a tiny `dt` (e.g. `1e-5`, `1e-12`) so per-step moves are measurable.
- Token expiry tests use real wall-clock offsets: `time.time() + 3600` for valid, a past value for expired. There is no clock-freezing library.

## Fixtures and Test Data

**Test data:**
- Token builders: `make_token(**claims)` creates an unsigned JWT-shaped string from a claim dict (`backend/tests/market/test_dhan_auth.py`, `backend/tests/market/test_factory_stream.py`). The same helper is duplicated in both files; if a third copy appears, move it to `dhan_fakes.py`.
- Instrument CSV: an inline multi-line string `CSV_TEXT` with a few NSE rows, parsed with `InstrumentResolver.from_csv` (`test_dhan_source.py`).
- Bars: small literal `Bar(date(...), open, high, low, close, volume)` lists.
- Credentials constant: `CREDENTIALS = Credentials("tok", "1100", time.time() + 3600)` at module level.

**Location:**
- There is no shared fixture directory. Inline data at module top, fixtures in the test module.

## Coverage

**Requirements:** no threshold enforced in configuration (`--cov-fail-under` is not set). The team target, recorded in `Docs/help.md` and PLAN.md §13, is 100% line coverage of `app/`.

**View Coverage:**
```bash
cd backend && uv run pytest --cov=app --cov-report=term-missing
```

## Test Types

**Unit Tests:**
- The bulk of the suite (about 125 market data tests plus 38 demo tests). Each test targets one module or one behaviour.
- Pure functions and dataclass properties are tested directly (`backend/tests/market/test_models_cache.py`).

**Integration Tests (in-process, still pytest):**
- `DhanDataSource` end to end: fake socket -> `DhanFeed` -> `PriceCache` (`backend/tests/market/test_dhan_source.py`).
- Console demo driven by typed input through `prompt_toolkit.input.create_pipe_input` and `DummyOutput` (`backend/tests/demo/test_console.py`). This runs the real full-screen app headless.
- Stream router and factory selection (`backend/tests/market/test_factory_stream.py`).
- No test starts uvicorn or hits the real Dhan service. The real-service checks were manual (PLAN.md §13, DHANHQ_API.md §9).

**E2E Tests:**
- Not used yet. The planned Playwright suite under `test/` (PLAN.md §4, §12) does not exist.

**Not yet covered by tests:**
- FastAPI app wiring, REST routes (`/api/portfolio`, `/api/watchlist`, `/api/chat`, `/api/health`), database (`backend/db/`), LLM integration, and the frontend. Add tests with each component, following the patterns above.

## Common Patterns

The snippets below are illustrative shapes, not copied test names. Check the cited files for the real tests.

**Async source lifecycle (illustrative):**
```python
async def test_remove_is_idempotent(parts):
    source, _ = build(parts, [...])
    await source.start(["TCS"])
    await source.remove_ticker("TCS")
    await source.remove_ticker("TCS")
    await source.stop()
```

**Stream events:** `price_events` in `backend/app/market/stream.py` yields `data:` frames; test it by consuming the generator and decoding the JSON payload.

**Error Testing (illustrative):**
```python
def test_malformed_token_is_rejected():
    with pytest.raises(AuthenticationError):
        credentials_from_token("not-a-jwt")
```
Use `pytest.raises` with the `MarketDataError` subclass named in the spec. Check the message only when it is part of the contract.

**Expiry and token validity (illustrative):**
```python
def test_expired_token_is_rejected():
    token = make_token(exp=time.time() - 60, dhanClientId="1100")
    with pytest.raises(AuthenticationError):
        credentials_from_token(token)
```

## Writing New Tests: Checklist

1. Put the file in the matching `backend/tests/<area>/` directory and name it `test_<module>.py`.
2. Use a one-line module docstring.
3. Write plain `def` or `async def` functions; no marker needed for async.
4. Use real domain objects; fake only the network, environment, and rare-event constants.
5. Use `monkeypatch` for module constants and `env=` for environment.
6. Seed randomness; use tolerances for statistical checks.
7. Use `until(...)` or `asyncio.sleep(0)` for background tasks, not long sleeps.
8. Run `uv run pytest` and `uv run ruff check .` from `backend/` before committing.

---

*Testing analysis: 2026-10-27*
