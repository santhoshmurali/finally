"""Fixed LLM reply used when LLM_MOCK=true. Keeps E2E tests fast and deterministic."""

from app.llm.schemas import LLMReply, LLMTrade

MOCK_REPLY = LLMReply(
    message="Bought 1 TCS (mock reply).",
    trades=[LLMTrade(ticker="TCS", quantity=1, side="buy")],
    watchlist_changes=[],
)
