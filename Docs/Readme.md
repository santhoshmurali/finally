# FinAlly - Documentation

AI trading workstation for Indian markets (NSE, INR). Full specification: [planning/PLAN.md](../planning/PLAN.md); implementation status: PLAN.md section 13.

## Status

| Area | State |
|---|---|
| Market data backend (Dhan WebSocket feed, simulator, unified interface, SSE stream) | Done, tested |
| Console demo: live table with per-symbol line charts (`uv run python -m demo`) | Done, tested |
| Database, portfolio/trade/watchlist APIs, LLM chat (mock mode), frontend, Docker, E2E | Done, tested: backend 252, frontend 49, E2E 10/10 locally and in the container |
| Docker | `scripts/start_windows.ps1` and `scripts/stop_windows.ps1` verified from a clean state: start builds and reports healthy, stop removes the container and image and keeps `finally-data`. The macOS scripts are not part of testing |

## Market data in one paragraph

`backend/app/market/` exposes one interface, `MarketDataSource`, with two implementations. With `DHAN_ACESS_TOKEN` set it streams live NSE prices from the DhanHQ Live Market Feed WebSocket; otherwise it runs a GBM simulator. Both write to a `PriceCache` that feeds `GET /api/stream/prices` (SSE).

## Quick start

```bash
cd backend
uv run pytest                       # 163 tests
uv run python -m demo               # live NSE watchlist in the console (add --simulator for no token)
```

## Where to read more

| Doc | Content |
|---|---|
| [planning/MARKET_DATA_DESIGN.md](../planning/MARKET_DATA_DESIGN.md) | Architecture, failure handling, tests |
| [planning/MARKET_INTERFACE.md](../planning/MARKET_INTERFACE.md) | The Python API |
| [planning/DHANHQ_API.md](../planning/DHANHQ_API.md) | Dhan provider reference and live findings |
| [planning/MARKET_SIMULATOR.md](../planning/MARKET_SIMULATOR.md) | Simulator model |
| [help.md](help.md) | Tutorials and lessons learnt |
