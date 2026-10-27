"""Prompt for the chat assistant: system instructions, portfolio context and history."""

from app.services.portfolio import PortfolioView, PositionView
from app.services.watchlist import WatchlistView
from db.models import ChatMessage

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant for a simulated portfolio of \
Indian equities listed on the NSE. All money is in INR.

Analyse the portfolio's composition, risk concentration and P&L. Suggest trades with short \
reasoning. Execute trades when the user asks for them or agrees to them. Manage the watchlist \
proactively. Be concise and data-driven.

Trades fill immediately at the current market price, so include a trade only when the user \
wants it. Use an empty list when there are no trades or watchlist changes. Always reply with \
the JSON structure requested."""


def build_messages(
    portfolio: PortfolioView,
    watchlist: list[WatchlistView],
    history: list[ChatMessage],
    message: str,
) -> list[dict]:
    """Chat messages: system prompt, past turns, then the new message with live context."""
    context = format_context(portfolio, watchlist)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *[{"role": item.role, "content": item.content} for item in history],
        {"role": "user", "content": f"{context}\n\nUser message: {message}"},
    ]


def format_context(portfolio: PortfolioView, watchlist: list[WatchlistView]) -> str:
    """Portfolio and watchlist as plain text for the LLM."""
    return "\n".join(
        [
            "Portfolio (INR):",
            f"Cash: {portfolio.cash_balance:,.2f}",
            f"Total value: {portfolio.total_value:,.2f}",
            f"Unrealized P&L: {portfolio.unrealized_pnl:,.2f}",
            "Positions:",
            *_position_lines(portfolio.positions),
            "Watchlist:",
            *_watchlist_lines(watchlist),
        ]
    )


def _position_lines(positions: list[PositionView]) -> list[str]:
    if not positions:
        return ["- none"]
    return [
        f"- {p.ticker}: quantity {p.quantity:g}, avg cost {p.avg_cost:,.2f}, "
        f"price {p.current_price:,.2f}, value {p.market_value:,.2f}, "
        f"unrealized P&L {p.unrealized_pnl:,.2f} ({p.unrealized_pnl_percent:.2f}%), "
        f"day change {p.day_change_percent:.2f}%"
        for p in positions
    ]


def _watchlist_lines(watchlist: list[WatchlistView]) -> list[str]:
    if not watchlist:
        return ["- none"]
    return [
        f"- {w.ticker}: no price yet"
        if w.price is None
        else f"- {w.ticker}: price {w.price:,.2f}, day change {w.day_change_percent:.2f}%"
        for w in watchlist
    ]
