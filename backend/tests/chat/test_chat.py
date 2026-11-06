"""Chat turns: model call, auto-execution of trades and watchlist changes, persistence."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.chat import ChatService
from app.llm import client as llm_client
from app.llm.client import LiteLLMChatModel, LLMError, MockChatModel
from app.llm.prompt import SYSTEM_PROMPT
from app.llm.schema import ChatReply, TradeAction, WatchlistAction
from app.market import PriceCache
from app.portfolio import PortfolioService
from app.priced_set import priced_tickers
from app.watchlist import WatchlistService
from db import Database
from tests.fakes import FakeSource

WATCHLIST = ("TCS", "INFY")
PRICES = {"TCS": 100.0, "INFY": 50.0, "WIPRO": 30.0}


class ScriptedModel:
    """Returns queued replies and remembers every message list it was given."""

    def __init__(self, *replies: ChatReply) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    async def reply(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.fixture
async def make_chat(tmp_path):
    async def build(*replies: ChatReply):
        cache = PriceCache()
        db = Database(tmp_path / "finally.db", WATCHLIST)
        source = FakeSource(cache, PRICES)
        await source.start(priced_tickers(db))
        portfolio = PortfolioService(db, cache, source)
        watchlist = WatchlistService(db, cache, source)
        model = ScriptedModel(*replies)
        return ChatService(db, portfolio, watchlist, model), portfolio, watchlist, db, model

    return build


async def test_mock_model_executes_fixed_trade_and_reports_it(make_chat):
    chat, portfolio, _, _, _ = await make_chat()
    chat.model = MockChatModel()

    reply = await chat.reply("hello")

    assert reply["trades"] == [{"ticker": "TCS", "side": "buy", "quantity": 1, "price": 100.0}]
    assert reply["watchlist_changes"] is None
    assert portfolio.get_portfolio().positions[0].ticker == "TCS"


async def test_watchlist_changes_are_applied_and_listed(make_chat):
    chat, _, watchlist, _, _ = await make_chat(
        ChatReply(
            message="Adding WIPRO and dropping INFY.",
            watchlist_changes=[
                WatchlistAction(ticker="WIPRO", action="add"),
                WatchlistAction(ticker="INFY", action="remove"),
            ],
        )
    )

    reply = await chat.reply("track wipro")

    assert reply["watchlist_changes"] == [
        {"ticker": "WIPRO", "action": "add"},
        {"ticker": "INFY", "action": "remove"},
    ]
    tickers = {entry.ticker for entry in watchlist.list_tickers()}
    assert tickers == {"TCS", "WIPRO"}


async def test_failed_trade_is_reported_in_message_and_not_listed(make_chat):
    chat, portfolio, _, _, model = await make_chat(
        ChatReply(
            message="Buying a lot.",
            trades=[TradeAction(ticker="TCS", quantity=1_000_000, side="buy")],
        )
    )

    reply = await chat.reply("go big")

    assert reply["trades"] is None
    assert "Trade not executed" in reply["message"]
    assert "insufficient cash" in reply["message"]
    assert portfolio.get_portfolio().cash_balance == 1_000_000.0
    assert len(model.calls) == 1


async def test_duplicate_watchlist_add_is_reported_not_raised(make_chat):
    chat, _, _, _, _ = await make_chat(
        ChatReply(
            message="Adding TCS.",
            watchlist_changes=[WatchlistAction(ticker="TCS", action="add")],
        )
    )

    reply = await chat.reply("add tcs")

    assert reply["watchlist_changes"] is None
    assert "already on the watchlist" in reply["message"]


async def test_turn_is_persisted_and_next_call_sees_history_and_context(make_chat):
    first = ChatReply(message="Here is your portfolio.")
    second = ChatReply(message="Still here.")
    chat, _, _, db, model = await make_chat(first, second)

    await chat.reply("how am I doing?")
    await chat.reply("and now?")

    with db.connect() as conn:
        rows = conn.execute("SELECT role, content FROM chat_messages ORDER BY rowid").fetchall()
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]

    first_call, second_call = model.calls
    assert first_call[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert "Portfolio context (JSON)" in first_call[-1]["content"]
    assert "how am I doing?" in first_call[-1]["content"]
    roles_second = [message["role"] for message in second_call]
    assert roles_second == ["system", "user", "assistant", "user"]


async def test_schema_rejects_unknown_side():
    with pytest.raises(ValidationError):
        TradeAction(ticker="TCS", quantity=1, side="short")


async def test_schema_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        TradeAction(ticker="TCS", quantity=0, side="buy")


def fake_completion(content: str):
    async def completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return completion


async def test_litellm_model_parses_structured_reply(monkeypatch):
    payload = ChatReply(message="ok", trades=[TradeAction(ticker="TCS", quantity=2, side="buy")])
    monkeypatch.setattr(llm_client, "acompletion", fake_completion(payload.model_dump_json()))

    reply = await LiteLLMChatModel("key").reply([{"role": "user", "content": "hi"}])

    assert reply == payload


async def test_litellm_model_rejects_malformed_reply(monkeypatch):
    monkeypatch.setattr(llm_client, "acompletion", fake_completion("not json"))

    with pytest.raises(LLMError):
        await LiteLLMChatModel("key").reply([{"role": "user", "content": "hi"}])


async def test_litellm_model_without_key_fails_at_call_time():
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        await LiteLLMChatModel("").reply([{"role": "user", "content": "hi"}])
