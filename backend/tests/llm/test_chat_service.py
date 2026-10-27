import pytest

from app.llm import chat_service
from app.llm.chat_service import handle_chat
from app.llm.errors import LLMError
from app.llm.schemas import LLMReply, LLMTrade, LLMWatchlistChange
from db.chat import list_chat_messages
from db.connection import transaction
from db.profile import get_cash_balance
from db.watchlist import list_watchlist

STARTING_CASH = 1_000_000.0


def stub_reply(monkeypatch, reply: LLMReply) -> None:
    """Make the LLM call return `reply` without any network access."""

    async def fake_request_reply(messages):
        return reply

    monkeypatch.setattr(chat_service, "request_reply", fake_request_reply)


def read_history():
    with transaction() as conn:
        return list_chat_messages(conn)


def read_cash() -> float:
    with transaction() as conn:
        return get_cash_balance(conn)


async def test_trade_executes_and_turn_is_stored(state, monkeypatch):
    trade = LLMTrade(ticker="tcs", quantity=2, side="buy")
    stub_reply(monkeypatch, LLMReply(message="Buying TCS.", trades=[trade]))

    response = await handle_chat(state, "Buy 2 TCS")

    assert response.message == "Buying TCS."
    assert [(t.ticker, t.quantity, t.side, t.price) for t in response.trades] == [
        ("TCS", 2, "buy", 2500.0)
    ]
    assert response.watchlist_changes is None
    assert read_cash() == STARTING_CASH - 5000.0
    user, assistant = read_history()
    assert (user.role, user.content, user.actions) == ("user", "Buy 2 TCS", None)
    assert assistant.actions == {
        "trades": [{"ticker": "TCS", "quantity": 2, "side": "buy", "price": 2500.0}],
        "watchlist_changes": None,
    }


async def test_rejected_trade_is_left_out_and_its_reason_appended(state, monkeypatch):
    stub_reply(
        monkeypatch,
        LLMReply(
            message="Two buys.",
            trades=[
                LLMTrade(ticker="TCS", quantity=1, side="buy"),
                LLMTrade(ticker="TCS", quantity=10_000_000, side="buy"),
            ],
        ),
    )

    response = await handle_chat(state, "Buy a lot")

    assert len(response.trades) == 1
    assert response.trades[0].quantity == 1
    assert response.message.startswith("Two buys. Insufficient cash")


async def test_watchlist_add_and_remove_are_applied(state, monkeypatch):
    stub_reply(
        monkeypatch,
        LLMReply(
            message="Updated the watchlist.",
            watchlist_changes=[
                LLMWatchlistChange(ticker="wipro", action="add"),
                LLMWatchlistChange(ticker="ITC", action="remove"),
            ],
        ),
    )

    response = await handle_chat(state, "Track WIPRO, drop ITC")

    assert [(c.ticker, c.action) for c in response.watchlist_changes] == [
        ("WIPRO", "add"),
        ("ITC", "remove"),
    ]
    with transaction() as conn:
        tickers = [entry.ticker for entry in list_watchlist(conn)]
    assert "WIPRO" in tickers
    assert "ITC" not in tickers
    assert read_history()[1].actions == {
        "trades": None,
        "watchlist_changes": [
            {"ticker": "WIPRO", "action": "add"},
            {"ticker": "ITC", "action": "remove"},
        ],
    }


async def test_rejected_watchlist_changes_are_reported(state, monkeypatch):
    stub_reply(
        monkeypatch,
        LLMReply(
            message="Tried.",
            watchlist_changes=[
                LLMWatchlistChange(ticker="NOPE", action="add"),
                LLMWatchlistChange(ticker="ZZZ", action="remove"),
            ],
        ),
    )

    response = await handle_chat(state, "Change the watchlist")

    assert response.watchlist_changes is None
    assert "NOPE" in response.message
    assert "ZZZ is not on the watchlist" in response.message


async def test_llm_failure_stores_nothing(state, monkeypatch):
    async def failing_request_reply(messages):
        raise LLMError("provider down")

    monkeypatch.setattr(chat_service, "request_reply", failing_request_reply)

    with pytest.raises(LLMError):
        await handle_chat(state, "Hello")
    assert read_history() == []


async def test_mock_mode_runs_the_fixed_trade(state, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")

    response = await handle_chat(state, "Anything")

    assert response.message == "Bought 1 TCS (mock reply)."
    assert response.trades[0].ticker == "TCS"
    assert read_cash() == STARTING_CASH - 2500.0


async def test_history_is_oldest_first_across_turns(state, monkeypatch):
    stub_reply(monkeypatch, LLMReply(message="First answer."))
    await handle_chat(state, "First question")
    stub_reply(monkeypatch, LLMReply(message="Second answer."))
    await handle_chat(state, "Second question")

    assert all(m.actions is None for m in read_history())
    assert [m.content for m in read_history()] == [
        "First question",
        "First answer.",
        "Second question",
        "Second answer.",
    ]
