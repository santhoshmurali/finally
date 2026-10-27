# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — ₹10,00,000 virtual cash, NSE stocks, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or live NSE prices from the DhanHQ WebSocket feed (when a Dhan token is set)

## Quick Start

Windows (PowerShell), with Docker Desktop running:

```powershell
# Configure
copy .env.example .env
# Add OPENROUTER_API_KEY and, optionally, DHAN_ACESS_TOKEN to .env

# Start (builds the image if needed) and stop (removes the container and image, keeps data)
.\scripts\start_windows.ps1
.\scripts\stop_windows.ps1

# Open http://localhost:8000
```

Local development (no Docker):

```bash
cd backend
uv run --env-file ../.env uvicorn app.main:app --port 8000
```

See [Docs/help.md](Docs/help.md) for tests, the console demo and lessons learnt.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | For live chat | OpenRouter API key for AI chat |
| `DHAN_ACESS_TOKEN` | No | DhanHQ access token for live NSE prices; empty uses the simulator. Expires after 24 hours |
| `DHAN_CLIENT_ID` | No | Overrides the client ID inside the Dhan token |
| `MARKET_SEED` | No | Integer that makes the simulator reproducible |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project (app/, db/, demo/, tests/)
├── planning/    # Project documentation and agent contracts
├── Docs/        # Readme and help (tutorials and lessons learnt)
├── test/        # Playwright E2E tests
├── scripts/     # Start/stop scripts (Windows verified; macOS not in testing)
└── Dockerfile   # Multi-stage build: Node builds the UI, Python serves it
```

## License

See [LICENSE](LICENSE).
