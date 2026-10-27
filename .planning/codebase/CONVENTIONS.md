---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# Coding Conventions

**Analysis Date:** 2026-10-27

## Scope of Code Today

Only the market data layer and the console demo are implemented, all Python under `backend/`. There is no frontend code, no FastAPI app wiring, and no database code yet. Conventions below are taken from `backend/app/`, `backend/demo/`, and `backend/tests/`. Frontend conventions are not yet established.

## Naming Patterns

**Files:**
- Modules are `snake_case.py`, named after the concept they hold: `cache.py`, `simulator.py`, `seed_prices.py`, `synthetic_history.py` in `backend/app/market/`.
- Vendor-specific code lives in a subpackage: `backend/app/market/dhan/` with `auth.py`, `client.py`, `feed.py`, `instruments.py`, `packets.py`, `source.py`.
- Test modules are `test_<subject>.py`, mirroring the source: `backend/tests/market/test_simulator.py` tests `app/market/simulator.py`.
- Shared test helpers do not use the `test_` prefix: `backend/tests/market/dhan_fakes.py`.

**Functions:**
- `snake_case`, verb-first for actions: `add_ticker`, `remove_ticker`, `daily_bars`, `credentials_from_token`, `token_from_env`, `seed_price_for`.
- Private helpers are prefixed with a single underscore and live at module level or as methods: `_validated` and `_correlation` in `backend/app/market/simulator.py`, `_pick_close` in `backend/app/market/cache.py`, `_on_packet` in `backend/app/market/dhan/source.py`.
- Factory functions use `create_` prefix: `create_market_source` in `backend/app/market/factory.py`, `create_stream_router` in `backend/app/market/stream.py`.
- Boolean-like queries read as predicates: `healthy()`, `is_disconnected()`.

**Variables:**
- `snake_case`, descriptive over abbreviated: `previous_close`, `day_change_percent`, `last_version`.
- Module-level constants are `UPPER_SNAKE_CASE`: `UPDATE_INTERVAL` and `EVENT_PROBABILITY` in `backend/app/market/simulator.py`, `STREAM_INTERVAL` and `RETRY_MILLISECONDS` in `backend/app/market/stream.py`, `TOKEN_ENV_NAMES` in `backend/app/market/dhan/auth.py`.
- Lookup tables are constants too: `SEED_PRICES`, `TICKER_PARAMS`, `DEFAULT_WATCHLIST` in `backend/app/market/seed_prices.py`.
- Short single-letter names appear only for loop indices and math (`i`, `j`, `n`, `dt`, `mu`, `sigma`), matching the GBM formula.
- Ticker symbols are upper-case strings. Sources normalise input with `.upper()` (see `DhanDataSource.add_ticker` in `backend/app/market/dhan/source.py`).

**Types and classes:**
- `PascalCase`: `PriceUpdate`, `PriceCache`, `GBMSimulator`, `SimulatorDataSource`, `MarketDataSource`, `DhanDataSource`, `UnsupportedTickerError`.
- Error classes end in `Error` and inherit from one base, `MarketDataError` (`backend/app/market/errors.py`).
- Source implementations end in `DataSource` (`SimulatorDataSource`, `DhanDataSource`). The abstract base is `MarketDataSource`.

## Code Style

**Formatting:**
- Line length 100 (`[tool.ruff] line-length = 100` in `backend/pyproject.toml`).
- Double quotes for strings, trailing commas in multi-line literals.
- `ruff format` is **not enforced**. Running `uv run ruff format --check .` in `backend/` reports 11 files that would be reformatted, including `backend/app/market/seed_prices.py` (the watchlist literal is packed several names per line), `backend/app/market/dhan/client.py`, `backend/demo/live_console.py`, and `backend/demo/render.py`. Treat `ruff format` as a recommendation for new code, not a gate.

**Linting:**
- Tool: Ruff, configured in `backend/pyproject.toml`: `select = ["E", "F", "I", "UP", "B"]`.
- Rule families in use: pycodestyle errors (E), pyflakes (F), isort ordering (I), pyupgrade (UP, which drives modern syntax such as `X | None` and builtin generics `dict[str, float]`), and flake8-bugbear (B).
- `uv run ruff check .` passes on the current tree. Run it before committing (`Docs/help.md` lists `uv run ruff check app tests`).

**Modern syntax:**
- Use `X | None` instead of `Optional[X]` (for example `float | None` in `backend/app/market/cache.py`).
- Builtin generics: `dict[str, float]`, `list[str]`, `set[str]`.
- `from __future__ import annotations` is at the top of most modules (`backend/app/market/cache.py`, `models.py`, `simulator.py`, `source.py`, `factory.py`, `interface.py`). It is absent from a few small modules (`errors.py`, `seed_prices.py`, the package `__init__.py` files). Add it to any module with type hints that reference later-defined names.

## Import Organization

**Order (enforced by Ruff `I`):**
1. Standard library (`import asyncio`, `from dataclasses import dataclass`)
2. Third-party (`import numpy as np`, `from fastapi import APIRouter`, `import httpx`)
3. Local package, relative inside `app/` (`from .cache import PriceCache`, `from ..interface import MarketDataSource`)

Example from `backend/app/market/dhan/source.py`:
```python
import asyncio
from datetime import date

import httpx

from ..cache import PriceCache
from ..interface import MarketDataSource
from ..models import Bar
from .auth import Credentials
```

**Cross-package imports:** the demo and tests import the app as an absolute package: `from app.market import DEFAULT_WATCHLIST, PriceCache` (`backend/demo/live_console.py`, `backend/tests/market/test_simulator.py`). Inside `app/`, always use relative imports.

**Public surface:**
- `backend/app/market/__init__.py` re-exports the public API and declares `__all__`. Consumers import from `app.market`, not from submodules, unless they need a private-ish detail (tests import `app.market.simulator` for module-level constants).
- Keep the `__all__` list sorted (the current file sorts constants, then classes, then functions).

**Path Aliases:**
- None. The project does not use path aliases.

## Type Hints and Data Modelling

- Public functions and methods carry full type hints; return types are declared (`-> PriceUpdate`, `-> dict[str, float]`, `-> None`).
- Value objects are frozen dataclasses with `slots=True`: `PriceUpdate` and `Bar` in `backend/app/market/models.py`, `Credentials` in `backend/app/market/dhan/auth.py`.
- Derived values are `@property` on the dataclass, not stored fields (`PriceUpdate.change`, `direction`, `day_change`, `day_change_percent`).
- JSON shaping is an explicit `to_dict()` method on the dataclass (`PriceUpdate.to_dict`), not a generic serializer.
- Secrets: `Credentials.__repr__` is overridden to omit the token (`backend/app/market/dhan/auth.py`). Keep that pattern for any new credential type.

## Numeric and Money Conventions

- All prices are INR floats rounded to two decimals at the cache boundary: `round(price, 2)` in `PriceCache.update`.
- Derived changes are rounded to four decimals (`round(self.price - self.previous_price, 4)` in `PriceUpdate.change`).
- Percent changes are expressed in percent units, not fractions: `day_change_percent` returns `12.5` for +12.5%. A zero previous close returns `0.0` rather than dividing by zero.
- Simulator maths keeps unrounded floats internally and rounds only on output (`GBMSimulator.step` returns `{t: round(p, 2) ...}`).
- Market-hours constants are named in the code, e.g. `NSE_TRADING_SECONDS_PER_YEAR = 252 * 6.25 * 3600` in `backend/app/market/simulator.py`.

## Error Handling

**Pattern: one exception hierarchy at the boundary.** Library and HTTP exceptions are translated into `MarketDataError` subclasses so callers never see provider types:
- `UnsupportedTickerError`: unknown symbol (`backend/app/market/errors.py`)
- `AuthenticationError`: bad, expired, or unentitled credentials. Not retryable.
- `RateLimitError`: throttled. Retry with backoff.
- `DataUnavailableError`: network, 5xx, or malformed reply.

Translate with explicit chaining, catching only the exceptions you expect:
```python
try:
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    ...
except (IndexError, KeyError, TypeError, ValueError) as exc:
    raise AuthenticationError("Dhan access token is not a valid JWT") from exc
```
(from `credentials_from_token` in `backend/app/market/dhan/auth.py`)

**Validation at the edge, fail early:** `DhanDataSource.start` resolves every security ID before subscribing, so an unknown symbol fails before any network subscribe. `SimulatorDataSource.start` validates tickers with `_validated` first.

**Idempotent operations:** `add_ticker`, `remove_ticker`, and `stop` are designed to be safe to call twice. Document this in the docstring of the abstract method (`backend/app/market/interface.py`) and keep it true in implementations.

**Do not add defensive code.** The team rule (root `CLAUDE.md` and the user's global `CLAUDE.md`) is to avoid defensive programming. Catch only where a specific failure has a specific response (reconnect, map to a `MarketDataError`, fall back in the demo CLI). Do not wrap internal calls in broad `try/except Exception`. None exist in `app/` today.

**Startup failure is loud:** an expired Dhan token stops startup with a clear error rather than silently simulating (`create_market_source` in `backend/app/market/factory.py` raises `AuthenticationError`). Do not add a silent fallback to the simulator.

## Async and Concurrency

- Long-running work is an `asyncio.Task` created with a name: `asyncio.create_task(self._run(), name="simulator")` in `backend/app/market/simulator.py`, `name="dhan-feed"` in `backend/app/market/dhan/source.py`.
- Stopping a task follows one pattern everywhere: cancel, gather with `return_exceptions=True`, then clear the reference:
```python
if self._task is not None:
    self._task.cancel()
    await asyncio.gather(self._task, return_exceptions=True)
    self._task = None
```
- Shared state read from SSE and written by sources is guarded by `threading.Lock` in `PriceCache` (`backend/app/market/cache.py`). Keep the lock for every mutation and for snapshot reads (`get_all` copies under the lock).
- Version counter: any cache mutation increments `version` so the SSE loop can skip unchanged ticks.
- The SSE loop polls with `await asyncio.sleep(interval)` and checks `request.is_disconnected()` (`backend/app/market/stream.py`).

## Dependency Injection

Collaborators are passed through constructor keyword arguments with defaults, so tests can substitute fakes without patching:
```python
def __init__(self, credentials, *, resolver=None, client=None, feed=None) -> None:
    self._client = client or DhanClient(credentials)
```
(`DhanDataSource` in `backend/app/market/dhan/source.py`). Environment is also injected: `create_market_source(cache, env=None)` takes a `Mapping[str, str]`, defaulting to `os.environ` (`backend/app/market/factory.py`).

## Environment Variables

- Names are `UPPER_SNAKE_CASE` and documented in `.env.example` and `planning/PLAN.md` §5.
- The Dhan token variable is spelled `DHAN_ACESS_TOKEN` (missing "c"). This spelling is the documented, primary name. `DHAN_ACCESS_TOKEN` is accepted as an alias (`TOKEN_ENV_NAMES` in `backend/app/market/dhan/auth.py`). Keep both when editing that code, and do not "fix" the primary name without updating the spec.
- Values are stripped of whitespace and surrounding quotes because `docker --env-file` preserves them (`token_from_env`).
- Read config with `.get(name, "").strip()` and convert types explicitly (`int(seed) if seed else None`).

## Logging

- No logging framework is used in `backend/app/` yet.
- The console demo writes to stdout with `print(..., flush=True)` (`backend/demo/live_console.py`). This is the only `print` use in the backend source outside tests.
- When adding server logging, use the standard `logging` module with a module-level `logger = logging.getLogger(__name__)`. Do not add `print` to `app/`.

## Comments and Docstrings

**Docstrings are the primary documentation:**
- Public classes and functions generally have a one-line or short multi-line docstring in triple double quotes. Examples: `PriceUpdate` (explains `previous_price` vs `previous_close`), `PriceCache.update`, `MarketDataSource` (describes the contract its consumers rely on).
- Docstrings state the contract, not the implementation: "Idempotent.", "Safe to call twice.", "Raises `UnsupportedTickerError` if unknown.", "`None` means not priced yet".
- Use backticks around identifiers and exception names.
- Module docstrings are a single line describing the module: `"""In-memory price cache: the single hand-off between price sources and consumers."""`

**Inline comments are sparing:**
- Used to explain a magic number inline, e.g. `EVENT_PROBABILITY = 0.001  # per ticker per step: about one shock a minute across ten tickers` in `backend/app/market/simulator.py`.
- Used for data provenance: `# INR prices from the NSE close of 2026-10-21. A seed price doubles as the previous close.` in `backend/app/market/seed_prices.py`.
- Use comments for "why", never for "what". Do not add comments that restate code.

**TODO/FIXME:** none in `backend/app/` or `backend/demo/`.

## Function Design

- Functions and methods are kept short and single-purpose; `GBMSimulator.step` is a representative example.
- Pure maths is separated from I/O: the GBM step and correlation are plain methods on `GBMSimulator`, testable without asyncio. The async wrapper `SimulatorDataSource` owns the task.
- Keyword-only arguments are used for optional collaborators (`*, resolver=None, client=None, feed=None`).
- Return values: return the new state (`PriceUpdate` from `PriceCache.update`) rather than `None` where the caller needs it. Mutators that do not need a result return `None`.
- Optional lookups return `None` (`PriceCache.get`, `get_price`), never raise, unless the caller must be told the input is wrong (then raise a `MarketDataError` subclass).

## Module Design

- One concept per module. The `market/` package splits along responsibility: `models.py` (value types), `errors.py`, `cache.py`, `interface.py` (ABC), `simulator.py`, `dhan/*`, `factory.py`, `stream.py`.
- Data-only modules hold constants and lookup tables (`seed_prices.py`) and no behaviour beyond a small helper.
- Barrel file: `backend/app/market/__init__.py` re-exports the public API. Do not import internal helpers through the barrel.
- Use `dataclass(frozen=True, slots=True)` for immutable records; use plain classes with explicit `__init__` for stateful services (`PriceCache`, `GBMSimulator`).

## Adding New Code: Checklist

1. Put vendor-specific code in its own subpackage, mirroring `backend/app/market/dhan/`.
2. Implement the existing abstract contract (`MarketDataSource`) rather than adding a parallel interface.
3. Translate provider errors into `MarketDataError` subclasses.
4. Type-hint public signatures; add `from __future__ import annotations`.
5. Write a docstring stating the contract.
6. Keep files and functions short; split when a module grows past a single concept.
7. Add tests under `backend/tests/<area>/` (see `TESTING.md`).
8. Run `uv run ruff check .` and `uv run pytest` from `backend/`.

---

*Convention analysis: 2026-10-27*
