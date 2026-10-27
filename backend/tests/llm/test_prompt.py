from app.llm.prompt import SYSTEM_PROMPT, build_messages, format_context
from app.services.portfolio import PortfolioView, PositionView
from app.services.watchlist import WatchlistView
from db.models import ChatMessage

EMPTY_PORTFOLIO = PortfolioView(
    cash_balance=1_000_000.0, total_value=1_000_000.0, unrealized_pnl=0.0, positions=[]
)


def test_context_lists_cash_and_empty_sections():
    text = format_context(EMPTY_PORTFOLIO, [])
    assert "Cash: 1,000,000.00" in text
    assert "Positions:\n- none" in text
    assert "Watchlist:\n- none" in text


def test_context_describes_positions_and_prices():
    position = PositionView(
        ticker="TCS",
        quantity=10,
        avg_cost=2500.0,
        current_price=2529.0,
        market_value=25290.0,
        unrealized_pnl=290.0,
        unrealized_pnl_percent=11.6,
        day_change_percent=0.4,
    )
    watchlist = [
        WatchlistView("TCS", "2026-10-27T10:00:00+00:00", 2529.0, 2520.0, 0.4),
        WatchlistView("WIPRO", "2026-10-27T10:00:00+00:00", None, None, None),
    ]
    text = format_context(
        PortfolioView(1.0, 26291.0, 290.0, [position]),
        watchlist,
    )
    assert "- TCS: quantity 10, avg cost 2,500.00, price 2,529.00" in text
    assert "unrealized P&L 290.00 (11.60%)" in text
    assert "- WIPRO: no price yet" in text


def test_messages_put_system_prompt_first_and_history_before_new_message():
    history = [
        ChatMessage("user", "Hi", None, "2026-10-27T10:00:00+00:00"),
        ChatMessage("assistant", "Hello", None, "2026-10-27T10:00:01+00:00"),
    ]
    messages = build_messages(EMPTY_PORTFOLIO, [], history, "Buy TCS")

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1:3] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"].endswith("User message: Buy TCS")
    assert "Cash: 1,000,000.00" in messages[-1]["content"]
