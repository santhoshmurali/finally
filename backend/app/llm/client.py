"""LLM clients: LiteLLM through OpenRouter to Cerebras, and a deterministic mock."""

from __future__ import annotations

from typing import Protocol

from litellm import acompletion

from app.llm.schema import ChatReply, TradeAction

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
MOCK_TRADE = TradeAction(ticker="TCS", quantity=1, side="buy")


class LLMError(Exception):
    """The model could not be reached or did not return a valid reply."""


class ChatModel(Protocol):
    async def reply(self, messages: list[dict[str, str]]) -> ChatReply:
        """Return the structured reply for `messages`."""


class LiteLLMChatModel:
    """Structured Outputs call through LiteLLM, OpenRouter and the Cerebras provider."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def reply(self, messages: list[dict[str, str]]) -> ChatReply:
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY is not set; set it or use LLM_MOCK=true")
        response = await acompletion(
            model=MODEL,
            messages=messages,
            response_format=ChatReply,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            api_key=self.api_key,
        )
        content = response.choices[0].message.content
        try:
            return ChatReply.model_validate_json(content)
        except ValueError as exc:
            raise LLMError(f"model returned an invalid reply: {exc}") from exc


class MockChatModel:
    """Deterministic replies with the same schema, for tests and offline runs."""

    async def reply(self, messages: list[dict[str, str]]) -> ChatReply:
        return ChatReply(
            message="Mock FinAlly: I bought 1 share of TCS for you.",
            trades=[MOCK_TRADE],
        )
