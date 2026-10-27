"""Snapshot history and chat message repository functions."""

from db.chat import insert_chat_message, list_chat_messages
from db.connection import transaction
from db.snapshots import insert_snapshot, list_snapshots


def record_values(values: list[float]) -> None:
    with transaction() as conn:
        for value in values:
            insert_snapshot(conn, value)


def test_list_snapshots_oldest_first(initialized_db):
    record_values([1.0, 2.0, 3.0])
    with transaction() as conn:
        snapshots = list_snapshots(conn, limit=None)
    assert [snapshot.total_value for snapshot in snapshots] == [1.0, 2.0, 3.0]
    assert snapshots[0].recorded_at


def test_limit_keeps_newest_rows_oldest_first(initialized_db):
    record_values([1.0, 2.0, 3.0, 4.0, 5.0])
    with transaction() as conn:
        snapshots = list_snapshots(conn, limit=2)
    assert [snapshot.total_value for snapshot in snapshots] == [4.0, 5.0]


def test_limit_zero_returns_nothing(initialized_db):
    record_values([1.0])
    with transaction() as conn:
        assert list_snapshots(conn, limit=0) == []


def test_empty_history_returns_empty_list(initialized_db):
    with transaction() as conn:
        assert list_snapshots(conn, limit=None) == []


def test_chat_messages_round_trip_with_actions(initialized_db):
    actions = [{"ticker": "TCS", "quantity": 1, "side": "buy", "price": 2529.0}]
    with transaction() as conn:
        insert_chat_message(conn, "user", "buy a TCS", None)
        insert_chat_message(conn, "assistant", "Bought 1 TCS.", actions)
    with transaction() as conn:
        user_message, assistant_message = list_chat_messages(conn)
    assert (user_message.role, user_message.content, user_message.actions) == (
        "user",
        "buy a TCS",
        None,
    )
    assert assistant_message.actions == actions
    assert assistant_message.created_at
