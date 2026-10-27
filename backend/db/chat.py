"""Conversation history with the assistant."""

import json
import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso
from .models import ChatMessage


def insert_chat_message(
    conn: sqlite3.Connection, role: str, content: str, actions: list[dict] | None
) -> None:
    """Store one message. `actions` is stored as JSON and is None for user messages."""
    encoded = None if actions is None else json.dumps(actions)
    conn.execute(
        """
        INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (new_id(), DEFAULT_USER_ID, role, content, encoded, now_iso()),
    )


def list_chat_messages(conn: sqlite3.Connection) -> list[ChatMessage]:
    """Full conversation, oldest first."""
    rows = conn.execute(
        """
        SELECT role, content, actions, created_at FROM chat_messages
        WHERE user_id = ? ORDER BY rowid
        """,
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [_to_message(row) for row in rows]


def _to_message(row: sqlite3.Row) -> ChatMessage:
    actions = None if row["actions"] is None else json.loads(row["actions"])
    return ChatMessage(
        role=row["role"],
        content=row["content"],
        actions=actions,
        created_at=row["created_at"],
    )
