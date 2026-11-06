# FinAlly - Documentation

AI trading workstation for Indian markets (NSE, INR). Full specification: [planning/PLAN.md](../planning/PLAN.md); implementation status: PLAN.md section 13. Day-to-day usage: [help.md](help.md).

## Status

| Area | State |
|---|---|
| Market data (Dhan WebSocket feed, simulator, unified interface, SSE stream) | Done, 125 tests |
| Console demo (`uv run python -m demo`) | Done, 38 tests |
| Database (schema, seed, lazy init) | Done, 5 tests |
| Portfolio: market orders, weighted cost, P&L, snapshots | Done, 22 tests |
| Watchlist service | Done, 10 tests |
| REST API, app wiring, health, static serving | Done, 14 API tests; smoke-tested under uvicorn and in Docker |
| LLM chat (LiteLLM, OpenRouter, Cerebras, structured output, mock mode) | Done, 10 tests; live model verified through the UI |
| Frontend (Next.js static export, all panels) | Done, 39 tests; lint and typecheck clean |
| Docker image, compose, start/stop scripts | Done; image runs healthy |
| Playwright E2E (`test/`) | Done: 7 simulator scenarios passing in Docker; 30 live scenarios passing in market hours (`test/live/`) |
| Functional scenarios (`test/functional/`) | Done: 13 live scenarios passing |

Backend: 226 tests. Frontend: 39. E2E: 7 simulator and 30 live. Functional: 13 live.

## Architecture in one paragraph

A single container serves everything on port 8000. FastAPI (`backend/app/`) owns the REST routes, the SSE price stream, the chat, and a SQLite database (`backend/db/`). A `MarketDataSource` writes live prices into a `PriceCache`: the Dhan feed when `DHAN_ACESS_TOKEN` is set, otherwise a GBM simulator. The portfolio and watchlist services execute trades and manage the priced set against that cache. The chat service calls the model through LiteLLM and OpenRouter (Cerebras), applies the trades and watchlist changes it returns, and stores the turn. The Next.js frontend (`frontend/`) is built as a static export and mounted by FastAPI at `/`.

## Layout

| Path | Contents |
|---|---|
| `backend/app/market/` | Market data interface, Dhan source, simulator, SSE stream |
| `backend/app/` | `main.py` (app factory and lifespan), `portfolio.py`, `watchlist.py`, `chat.py`, `repository.py`, `api/`, `llm/` |
| `backend/db/` | `schema.sql`, `Database` (lazy creation, seeding, connections) |
| `backend/demo/` | Console demo |
| `frontend/src/` | `app/` (page and layout), `components/`, `hooks/`, `lib/` (API client, tick history, treemap layout) |
| `test/` | Playwright suite and `docker-compose.test.yml` |
| `scripts/` | Start and stop scripts for macOS/Linux and Windows |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Container build and optional compose wrapper |

## Where to read more

| Doc | Content |
|---|---|
| [help.md](help.md) | Running, using, testing, API reference, and lessons learnt |
| [planning/PLAN.md](../planning/PLAN.md) | Product specification and implementation status |
| [planning/MARKET_DATA_SUMMARY.md](../planning/MARKET_DATA_SUMMARY.md) | Market data component summary |
| [planning/archive/](../planning/archive/) | Detailed market data design, interface, Dhan API notes, simulator model |
