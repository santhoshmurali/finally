"""SQLite persistence: schema, seed data and repository functions.

Every repository function takes an open connection as its first argument, so
services can group several writes in one `transaction()`.
"""

from .chat import insert_chat_message, list_chat_messages
from .connection import connect, init_db, transaction
from .models import ChatMessage, Position, Snapshot, Trade, WatchlistEntry
from .positions import delete_position, get_position, list_positions, save_position
from .profile import get_cash_balance, set_cash_balance
from .snapshots import insert_snapshot, list_snapshots
from .trades import insert_trade, list_trades
from .watchlist import add_watchlist, delete_watchlist, list_watchlist

__all__ = [
    "ChatMessage",
    "Position",
    "Snapshot",
    "Trade",
    "WatchlistEntry",
    "add_watchlist",
    "connect",
    "delete_position",
    "delete_watchlist",
    "get_cash_balance",
    "get_position",
    "init_db",
    "insert_chat_message",
    "insert_snapshot",
    "insert_trade",
    "list_chat_messages",
    "list_positions",
    "list_snapshots",
    "list_trades",
    "list_watchlist",
    "save_position",
    "set_cash_balance",
    "transaction",
]
