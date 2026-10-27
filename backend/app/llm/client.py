"""LiteLLM call to the Cerebras-hosted model through OpenRouter."""

import os

from litellm import acompletion
from openai import OpenAIError
from pydantic import ValidationError

from app.llm.errors import LLMError
from app.llm.mock import MOCK_REPLY
from app.llm.schemas import LLMReply

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}


def is_mock_mode() -> bool:
    """True when LLM_MOCK is set to true."""
    return os.environ.get("LLM_MOCK", "false").lower() == "true"


async def request_reply(messages: list[dict]) -> LLMReply:
    """Return the structured reply for the messages.

    Raises LLMError when the provider call fails or the reply does not match LLMReply.
    """
    if is_mock_mode():
        return MOCK_REPLY
    try:
        response = await acompletion(
            model=MODEL,
            messages=messages,
            response_format=LLMReply,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
        )
        return LLMReply.model_validate_json(response.choices[0].message.content)
    except (OpenAIError, ValidationError) as error:
        raise LLMError(str(error)) from error
