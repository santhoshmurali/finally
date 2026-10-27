"""Constants and helpers shared by the database modules."""

import uuid
from datetime import UTC, datetime

DEFAULT_USER_ID = "default"
STARTING_CASH = 1000000.0


def new_id() -> str:
    """Random UUID string for a primary key."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()
