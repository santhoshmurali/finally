---
last_mapped_commit: 372f4e98c6c62d67c9982ef0e8229ef2bb2bee92
last_mapped_at: 2026-10-27
---
# Technology Stack

**Analysis Date:** 2026-10-27

## Languages

**Primary:**
- Python 3.12+ - All implemented code: `backend/app/market/` (market data layer) and `backend/demo/` (console demo). Declared in `backend/pyproject.toml` (`requires-python = ">=3.12"`); the lockfile `backend/uv.lock` also pins `requires-python >=3.12`.

**Secondary:**
- TypeScript / Next.js - Planned, not yet present. The `frontend/` directory does not exist in the repo.
- SQL (SQLite dialect) - Planned, not yet present. Schema will live in `backend/db/` (not yet created).
- Bash / PowerShell - Planned start/stop scripts under `scripts/` (not yet present).

## Runtime

**Environment:**
- CPython 3.12 or newer (no `.python-version` file in the repo; the minimum is enforced only through `requires-python`).
- Target container runtime per PLAN.md section 11: Python 3.12 slim image, plus a Node 20 slim build stage for the frontend (Dockerfile not yet present).

**Package Manager:**
- `uv` (Astral) - manages the backend project, virtual environment, and lockfile.
- Lockfile: present - `backend/uv.lock` (lockfile version 1).
- No Node package manager is configured yet (no `frontend/package.json`).

## Frameworks

**Core:**
- FastAPI 0.159.1 (locked; `fastapi>=0.159.1` in `backend/pyproject.toml`) - HTTP API and SSE router. Only `create_stream_router` in `backend/app/market/stream.py` uses it so far. The app itself (lifespan, static file mounting) is not yet wired.
- Starlette 1.9.0 (locked, transitive via FastAPI) - routing and responses.
- Uvicorn 0.54.0 (locked; `uvicorn>=0.54.0`) - ASGI server; the planned container entry point (PLAN.md section 11).
- Pydantic 2.14.1 (locked, transitive via FastAPI) - not yet used directly in the repo.

**Testing:**
- pytest 9.1.1 (locked; dev group) - test runner. `asyncio_mode = "auto"` and `testpaths = ["tests"]` in `backend/pyproject.toml`.
- pytest-asyncio 1.4.0 (dev group) - async test support.
- pytest-cov 7.1.0 (dev group) - coverage reports.
- Frontend testing (React Testing Library, Playwright E2E in `test/`) - Planned, not yet present.

**Build/Dev:**
- ruff 0.17.1 (locked; dev group) - linting and formatting. Config in `backend/pyproject.toml` under `[tool.ruff]`: `line-length = 100`, lint rules `E`, `F`, `I`, `UP`, `B`.
- uv - dependency resolution, `uv run`, `uv sync` (see Configuration).
- Next.js (TypeScript, static export `output: 'export'`) - Planned, not yet present.
- Tailwind CSS - Planned for the frontend, not yet present.
- Canvas charting library (Lightweight Charts or Recharts) - Planned for the frontend, not yet present.
- Docker (multi-stage Node 20 -> Python 3.12) - Planned, not yet present (`Dockerfile` absent).

## Key Dependencies

**Critical (runtime, from `backend/pyproject.toml`):**
- `fastapi` 0.159.1 - API framework and SSE endpoint host (`backend/app/market/stream.py`).
- `uvicorn` 0.54.0 - ASGI server.
- `httpx` 0.28.1 - async HTTP client for Dhan REST history and instrument list (`backend/app/market/dhan/client.py`, `backend/app/market/dhan/instruments.py`). Dhan tests use `httpx` transports as fakes.
- `websockets` 17.3 - WebSocket client for the Dhan Live Market Feed (`backend/app/market/dhan/feed.py`).
- `numpy` 2.5.4 - numeric work for the GBM simulator (`backend/app/market/simulator.py`) and synthetic history (`backend/app/market/synthetic_history.py`).

**Demo and dev only (dependency groups):**
- `prompt-toolkit` 3.0.53 - group `demo`; full-screen console demo (`backend/demo/live_console.py`, `backend/demo/render.py`). Default dependency group per `[tool.uv] default-groups = ["dev", "demo"]`.
- `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff` - group `dev`.

**Standard library notable usage:**
- `struct`, `zlib`, `base64`, `json` - Dhan binary packet decoding and JWT claim parsing (`backend/app/market/dhan/packets.py`, `backend/app/market/dhan/auth.py`).
- `asyncio` - background market data tasks and the Dhan feed loop.
- `dataclasses` (with `slots=True`) - models such as `Credentials` in `backend/app/market/dhan/auth.py`.

**Planned, not yet in `pyproject.toml`:**
- An LLM client via LiteLLM (routing to OpenRouter, Cerebras inference provider) - PLAN.md section 9. Not yet added; add with `uv add litellm`.
- SQLite access - stdlib `sqlite3` or another driver, to be decided when `backend/db/` is built.

## Configuration

**Environment:**
- Configuration is read from environment variables. The backend reads `.env` from the project root (PLAN.md section 5). A `.env` file exists at the project root (contents not recorded here) and `.env.example` documents the variables.
- Variables in use by implemented code:
  - `DHAN_ACESS_TOKEN` - Dhan JWT access token. The misspelled name is the one in the spec; `DHAN_ACCESS_TOKEN` is also accepted. Read in `backend/app/market/dhan/auth.py` (`TOKEN_ENV_NAMES`). Surrounding quotes are stripped.
  - `DHAN_CLIENT_ID` - optional override of the client ID embedded in the token (`backend/app/market/factory.py`).
  - `MARKET_SEED` - optional integer for a reproducible simulator (`backend/app/market/factory.py`).
  - `OPENROUTER_API_KEY` - planned, consumed by the LLM layer (not yet implemented).
  - `LLM_MOCK` - planned; `true` selects deterministic mock LLM responses (not yet implemented).
- Source selection: `create_market_source()` in `backend/app/market/factory.py` picks Dhan when a token is set, otherwise the simulator. An expired or malformed token raises `AuthenticationError` rather than falling back.
- `.env.example` at the project root is the committed template.

**Build:**
- `backend/pyproject.toml` - project metadata, dependencies, dependency groups, pytest, ruff, and uv settings.
- `backend/uv.lock` - pinned dependency graph.
- Not yet present: `Dockerfile`, `docker-compose.yml`, `scripts/*.sh|*.ps1`, `frontend/package.json`, `frontend/next.config.*`, `test/docker-compose.test.yml`.

**CI:**
- GitHub Actions: `.github/workflows/claude.yml` (Claude Code bot on `@claude` mentions) and `.github/workflows/claude-code-review.yml` (automated PR review). No test or lint workflow is configured.

## Platform Requirements

**Development:**
- Windows, macOS, or Linux with Python 3.12+ and `uv` installed.
- Backend setup: `cd backend && uv sync` (installs default groups `dev` and `demo`).
- Run tests: `cd backend && uv run pytest`.
- Lint: `cd backend && uv run ruff check .`
- Live console demo: `cd backend && uv run python -m demo` (see `Docs/help.md`).
- Node.js 20 is required only once `frontend/` exists.

**Production:**
- Target: single Docker container on port 8000 (PLAN.md sections 3 and 11), with a named volume `finally-data` mounted at `/app/db` for `finally.db`. Not yet built.
- Deployment candidates named in the spec: AWS App Runner, Render, or any container platform. Optional Terraform under `deploy/` is a stretch goal.
- Production image must be built without the `dev` and `demo` dependency groups, because `prompt-toolkit` is in the `demo` group (PLAN.md section 13).

---

*Stack analysis: 2026-10-27*
