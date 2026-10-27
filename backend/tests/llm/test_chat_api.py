from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat
from app.llm import chat_service, client
from app.llm.errors import LLMError
from app.llm.schemas import LLMReply


@pytest.fixture
def http(state) -> TestClient:
    """Test client for the chat router with the shared app state (no lifespan)."""
    app = FastAPI()
    app.include_router(chat.router)
    app.state.app_state = state
    return TestClient(app)


def stub_reply(monkeypatch, reply: LLMReply) -> None:
    async def fake_request_reply(messages):
        return reply

    monkeypatch.setattr(chat_service, "request_reply", fake_request_reply)


def test_post_chat_returns_the_documented_shape(http, monkeypatch):
    stub_reply(monkeypatch, LLMReply(message="Hello there."))

    response = http.post("/api/chat", json={"message": "Hi"})

    assert response.status_code == 200
    assert response.json() == {"message": "Hello there.", "trades": None, "watchlist_changes": None}


def test_post_chat_returns_executed_trades(http, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")

    response = http.post("/api/chat", json={"message": "Buy"})

    body = response.json()
    assert response.status_code == 200
    assert body["trades"] == [{"ticker": "TCS", "quantity": 1, "side": "buy", "price": 2500.0}]
    assert body["watchlist_changes"] is None


def test_empty_message_is_a_validation_error(http):
    assert http.post("/api/chat", json={"message": ""}).status_code == 422


def test_malformed_llm_reply_gives_502_and_stores_nothing(http, monkeypatch):
    message = SimpleNamespace(content="not json")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def malformed(**kwargs):
        return response

    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setattr(client, "acompletion", malformed)

    assert http.post("/api/chat", json={"message": "Hi"}).status_code == 502
    assert http.get("/api/chat/history").json() == []


def test_provider_failure_gives_502(http, monkeypatch):
    async def failing_request_reply(messages):
        raise LLMError("provider down")

    monkeypatch.setattr(chat_service, "request_reply", failing_request_reply)

    assert http.post("/api/chat", json={"message": "Hi"}).status_code == 502


def test_history_returns_turns_oldest_first(http, monkeypatch):
    stub_reply(monkeypatch, LLMReply(message="Reply."))
    http.post("/api/chat", json={"message": "First"})
    http.post("/api/chat", json={"message": "Second"})

    history = http.get("/api/chat/history").json()

    assert [(item["role"], item["content"]) for item in history] == [
        ("user", "First"),
        ("assistant", "Reply."),
        ("user", "Second"),
        ("assistant", "Reply."),
    ]
    assert history[0]["actions"] is None
    assert set(history[0]) == {"role", "content", "actions", "created_at"}
