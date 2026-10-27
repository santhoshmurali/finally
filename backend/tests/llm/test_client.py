from types import SimpleNamespace

import pytest
from litellm.exceptions import ServiceUnavailableError

from app.llm import client
from app.llm.errors import LLMError
from app.llm.mock import MOCK_REPLY

VALID_REPLY_JSON = '{"message": "Holding steady.", "trades": [], "watchlist_changes": []}'
MESSAGES = [{"role": "user", "content": "hi"}]


def fake_acompletion(content: str | None, captured: dict | None = None):
    """Stand-in for litellm.acompletion that returns a reply with the given content."""
    message = SimpleNamespace(content=content)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def acompletion(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return response

    return acompletion


async def test_mock_mode_returns_fixed_reply_without_network(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")

    async def fail(**kwargs):
        raise AssertionError("provider must not be called in mock mode")

    monkeypatch.setattr(client, "acompletion", fail)
    assert await client.request_reply(MESSAGES) == MOCK_REPLY


async def test_real_mode_parses_structured_reply(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setattr(client, "acompletion", fake_acompletion(VALID_REPLY_JSON))
    reply = await client.request_reply(MESSAGES)
    assert reply.message == "Holding steady."


async def test_real_mode_sends_model_schema_and_cerebras_order(monkeypatch):
    captured: dict = {}
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setattr(client, "acompletion", fake_acompletion(VALID_REPLY_JSON, captured))
    await client.request_reply(MESSAGES)
    assert captured["model"] == "openrouter/openai/gpt-oss-120b"
    assert captured["response_format"] is client.LLMReply
    assert captured["extra_body"] == {"provider": {"order": ["cerebras"]}}


@pytest.mark.parametrize("content", ["not json", None])
async def test_malformed_reply_raises_llm_error(monkeypatch, content):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setattr(client, "acompletion", fake_acompletion(content))
    with pytest.raises(LLMError):
        await client.request_reply(MESSAGES)


async def test_provider_failure_raises_llm_error(monkeypatch):
    async def unavailable(**kwargs):
        raise ServiceUnavailableError(message="down", llm_provider="openrouter", model=client.MODEL)

    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setattr(client, "acompletion", unavailable)
    with pytest.raises(LLMError):
        await client.request_reply(MESSAGES)
