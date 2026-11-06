"""System prompt and message assembly for the FinAlly assistant."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant for a simulated Indian equity portfolio.
All prices are in INR (Rs) and tickers are NSE equity symbols such as TCS or RELIANCE.

Your job:
- Analyze the portfolio's composition, concentration risk and P&L.
- Suggest trades with short reasoning.
- Execute trades when the user asks for them or agrees to a suggestion.
- Manage the watchlist proactively when it helps the user.
- Be concise and data-driven.

Always respond with a single JSON object matching this schema:
{"message": string,
 "trades": [{"ticker": string, "quantity": number, "side": "buy" | "sell"}],
 "watchlist_changes": [{"ticker": string, "action": "add" | "remove"}]}
Use empty lists when there is nothing to execute. Quantities are positive numbers of shares.
"""


def build_messages(
    history: Sequence[dict[str, Any]], context: dict[str, Any], user_message: str
) -> list[dict[str, str]]:
    """System prompt, prior turns, then the new message with the live portfolio context."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": turn["role"], "content": turn["content"]} for turn in history)
    messages.append(
        {
            "role": "user",
            "content": (
                f"Portfolio context (JSON):\n{json.dumps(context)}\n\nUser message:\n{user_message}"
            ),
        }
    )
    return messages
