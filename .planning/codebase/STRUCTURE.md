---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# Codebase Structure

**Analysis Date:** 2026-10-27

## Directory Layout

```
finally/                          # repo root
├── backend/                      # Python uv project (present: market layer + demo)
│   ├── app/
│   │   ├── __init__.py           # empty package marker
│   │   └── market/               # market data: interface, cache, sources, SSE router
│   │       └── dhan/             # Dhan live feed, REST client, instruments, auth
│   ├── demo/                     # console demo (run with -m demo)
│   ├── tests/                    # pytest suites mirroring app/ and demo/
│   │   ├── demo/
│   │   └── market/
│   ├── pyproject.toml            # uv project, dependency groups (demo, dev)
│   └── uv.lock
├── frontend/                     # PLANNED: Next.js static export (not present)
├── planning/                     # project-wide specs and agent reference docs
│   ├── PLAN.md                   # master spec; section 13 = implementation status
│   ├── MARKET_DATA_SUMMARY.md
│   └── archive/                  # older planning docs (consult only when needed)
├── Docs/                         # Readme.md and help.md (user docs)
├── scripts/                      # PLANNED: start/stop scripts (not present)
├── test/                         # PLANNED: Playwright E2E tests (not present)
├── .claude/                      # GSD agent tooling and project skills
├── .github/workflows/            # claude.yml, claude-code-review.yml
├── .planning/                    # GSD working state; codebase/ holds these maps
├── .env.example                  # documented environment variables (committed)
├── CLAUDE.md                     # agent instructions for the repo
├── README.md
└── LICENSE
```

Not present yet, per `planning/PLAN.md` section 4: `backend/db/`, `Dockerfile`, `docker-compose.yml`, `scripts/`, `test/`, `frontend/`, and the FastAPI entry module under `backend/app/`.

## Directory Purposes

**`backend/app/market/`:**
- Purpose: All live and simulated price logic, plus the SSE route.
- Contains: `interface.py` (ABC), `models.py`, `errors.py`, `cache.py`, `factory.py`, `simulator.py`, `seed_prices.py`, `synthetic_history.py`, `stream.py`, `__init__.py` (public API).
- Key files: `backend/app/market/__init__.py`, `backend/app/market/factory.py`, `backend/app/market/interface.py`.

**`backend/app/market/dhan/`:**
- Purpose: Dhan-specific implementation of `MarketDataSource`.
- Contains: `source.py` (`DhanDataSource`), `feed.py` (WebSocket), `client.py` (REST history), `packets.py` (binary decoding), `instruments.py` (symbol to security ID), `auth.py` (token parsing). `__init__.py` is empty.
- Key files: `backend/app/market/dhan/source.py`, `backend/app/market/dhan/feed.py`.

**`backend/demo/`:**
- Purpose: Terminal demo of the market layer; not part of the application server.
- Contains: `__main__.py` (entry), `live_console.py` (prompt-toolkit app), `render.py` (table and chart rendering, `Command` and `PriceHistory` types).
- Key files: `backend/demo/live_console.py`, `backend/demo/render.py`.

**`backend/tests/`:**
- Purpose: Unit tests for market and demo code, with fakes instead of network I/O.
- Contains: `tests/market/test_*.py`, `tests/market/dhan_fakes.py` (scripted fake socket and HTTP), `tests/demo/test_console.py`, `tests/demo/test_render.py`.
- Key files: `backend/tests/market/test_simulator.py`, `backend/tests/market/test_dhan_feed.py`, `backend/tests/market/test_factory_stream.py`.

**`planning/`:**
- Purpose: Shared contract between agents; PLAN.md is authoritative.
- Contains: `PLAN.md`, `MARKET_DATA_SUMMARY.md`, `archive/`. The market design docs referenced from PLAN.md (`MARKET_DATA_DESIGN.md`, `MARKET_INTERFACE.md`, `DHANHQ_API.md`, `MARKET_SIMULATOR.md`) live in `planning/archive/`, not at the top level.

**`Docs/`:**
- Purpose: Human-facing readme and how-to (includes the demo run command).
- Contains: `Readme.md`, `help.md`.

**`.claude/`:**
- Purpose: Claude Code configuration, GSD command and agent definitions, GSD core references. Not application code.

**`.planning/`:**
- Purpose: GSD workflow state (`config.json`, `codebase/`). Untracked in git at the start of this session.

## Key File Locations

**Entry Points:**
- `backend/demo/__main__.py`: console demo entry (`python -m demo`).
- `backend/app/market/__init__.py`: public market API (import surface for future app code).
- FastAPI app module: not present.

**Configuration:**
- `backend/pyproject.toml`: Python version (>=3.12), runtime deps (fastapi, httpx, numpy, uvicorn, websockets), groups `demo` and `dev`, ruff line length 100, pytest asyncio mode.
- `.env.example`: environment variable template (do not commit real values).
- `backend/app/market/factory.py`: env-driven source selection.

**Core Logic:**
- `backend/app/market/cache.py`: price hand-off.
- `backend/app/market/simulator.py`: GBM simulator.
- `backend/app/market/dhan/feed.py`: live feed loop and reconnection.
- `backend/app/market/stream.py`: SSE endpoint.

**Testing:**
- `backend/tests/market/`: market layer unit tests.
- `backend/tests/demo/`: demo unit tests.
- `test/` (E2E): not present.

## Naming Conventions

**Files:**
- Python modules: `snake_case.py`, one concept per module (e.g., `packets.py`, `instruments.py`).
- Tests: `test_<module>.py` under `backend/tests/<package>/`; shared test helpers named `<package>_fakes.py` (`dhan_fakes.py`).
- Planning docs: `UPPER_SNAKE.md` (e.g., `PLAN.md`, `MARKET_DATA_SUMMARY.md`); generated codebase maps use `UPPERCASE.md`.

**Directories:**
- Lowercase, single word where possible (`market`, `demo`, `tests`); provider-specific sub-packages named after the provider (`dhan/`).

**Code identifiers:**
- Classes: `PascalCase`, source classes suffixed `DataSource` (`SimulatorDataSource`, `DhanDataSource`); errors suffixed `Error`.
- Functions and constants: `snake_case` functions, `UPPER_SNAKE` constants (`STREAM_INTERVAL`, `MAX_INSTRUMENTS_PER_MESSAGE`, `DEFAULT_WATCHLIST`).
- Environment variables: `UPPER_SNAKE` (`DHAN_ACESS_TOKEN`; note the spelling is intentional per PLAN.md section 5, with `DHAN_ACCESS_TOKEN` also accepted).

## Where to Add New Code

**New price source (another provider):**
- Implementation: `backend/app/market/<provider>/` subpackage implementing `MarketDataSource` from `backend/app/market/interface.py`.
- Wiring: add a branch in `backend/app/market/factory.py`.
- Tests: `backend/tests/market/test_<provider>_*.py` with fakes, plus a conformance check like `test_factory_stream.py`.

**New market utility shared by sources:**
- Implementation: `backend/app/market/` top level (for example next to `models.py`), exported from `backend/app/market/__init__.py` only if other packages need it.

**Database layer (planned):**
- Implementation: `backend/db/` per PLAN.md section 4 (schema SQL, seed, lazy init). Keep it outside `backend/app/market/`.

**Portfolio, trade, watchlist APIs (planned):**
- Implementation: a new package under `backend/app/` (for example `backend/app/portfolio/` and `backend/app/watchlist/`), with routers following the pattern of `backend/app/market/stream.py` (`create_*_router(...)` returning an `APIRouter`).
- Tests: `backend/tests/<package>/`.

**FastAPI app wiring (planned):**
- Implementation: a module under `backend/app/` that builds the app, lifespan (create cache and source, start, stop) and mounts `create_stream_router(cache)`.

**LLM integration (planned):**
- Implementation: a separate package under `backend/app/` (e.g., `backend/app/llm/`), using LiteLLM per PLAN.md section 9.

**Frontend (planned):**
- Implementation: `frontend/` as a self-contained Next.js project with static export; no Python knowledge.

**Console demo changes:**
- Implementation: `backend/demo/`; keep it free of application logic and use only `app.market` public exports.

**Utilities:**
- Shared helpers: `backend/app/market/` for market-specific helpers; no general `utils` package exists.

## Special Directories

**`backend/.venv/` and `__pycache__/`:**
- Purpose: Local uv virtual environment and bytecode.
- Generated: Yes
- Committed: No (covered by `.gitignore`)

**`.claude/gsd-core/`, `.claude/agents/`, `.claude/commands/`:**
- Purpose: GSD tooling installed into the repo.
- Generated: Yes (installed by GSD)
- Committed: Yes

**`.planning/codebase/`:**
- Purpose: Output of codebase mapping (these documents).
- Generated: Yes
- Committed: Caller decides (the repo currently lists `.planning/` as untracked)

**`planning/archive/`:**
- Purpose: Historical planning material.
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-10-27*
