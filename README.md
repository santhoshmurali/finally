# FinAlly — AI Trading Workstation

A dark, data-dense trading terminal for NSE stocks. Prices stream live, you trade a virtual ₹10,00,000 portfolio with market orders, and an AI assistant can analyse your holdings and execute trades through plain conversation.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live prices** over SSE, with green and red flash animations
- **Simulated portfolio**: ₹10,00,000 virtual cash, market orders, instant fills, no fees
- **Portfolio views**: treemap heatmap, value-over-time chart, positions table
- **AI chat assistant**: analyses holdings, suggests trades, and executes them immediately (no confirmation step), with inline confirmations
- **Watchlist management** by hand or through the chat

## Quick start

You need Docker Desktop running and an OpenRouter API key.

```bash
cp .env.example .env          # set OPENROUTER_API_KEY in .env
scripts/start_mac.sh          # macOS / Linux
scripts/start_windows.ps1     # Windows PowerShell
```

Open http://localhost:8000. Stop with `scripts/stop_mac.sh` or `scripts/stop_windows.ps1`; your data is kept in the `finally-data` volume.

Without an API key, set `LLM_MOCK=true` for deterministic chat replies. Without a Dhan token, prices come from the built-in simulator.

Full instructions, the API reference and the test commands are in [Docs/help.md](Docs/help.md).

## Architecture

One container on port 8000:

- **Frontend**: Next.js (static export), TypeScript, Tailwind CSS, Lightweight Charts
- **Backend**: FastAPI (Python, managed with uv), SSE for prices
- **Database**: SQLite, created on first use
- **AI**: LiteLLM → OpenRouter → Cerebras, with structured outputs
- **Market data**: live NSE prices from DhanHQ when `DHAN_ACESS_TOKEN` is set; otherwise a GBM simulator

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | For chat | OpenRouter API key |
| `LLM_MOCK` | No | `true` for deterministic mock chat replies |
| `DHAN_ACESS_TOKEN` | No | Dhan access token for live NSE data (needs the Data API plan) |
| `DHAN_CLIENT_ID` | No | Overrides the client ID inside the Dhan token |
| `MARKET_SEED` | No | Makes the simulator reproducible |

## Project structure

```
finally/
├── frontend/    # Next.js static export (TypeScript, Tailwind)
├── backend/     # FastAPI app, market data, database, LLM chat (uv project)
├── test/        # Playwright end-to-end tests and docker-compose.test.yml
├── planning/    # Specification and implementation status
├── Docs/        # Help and readme
├── scripts/     # Start and stop helpers
└── Dockerfile   # Multi-stage build: Node, then Python
```

## License

See [LICENSE](LICENSE).
