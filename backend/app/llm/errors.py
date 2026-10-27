"""Errors raised by the LLM layer. The chat route maps them to HTTP 502."""


class LLMError(Exception):
    """The LLM call failed or its reply did not match the schema."""
