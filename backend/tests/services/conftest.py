"""Fresh database and a deterministic price source for each service test."""

import pytest

from app.market import PriceCache
from app.state import AppState
from db.connection import init_db
from tests.app_fakes import FixedPriceSource


@pytest.fixture
def state(tmp_path, monkeypatch) -> AppState:
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    init_db()
    cache = PriceCache()
    return AppState(cache=cache, source=FixedPriceSource(cache))
