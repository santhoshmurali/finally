"""The full app with a deterministic price source and a temporary database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import main
from tests.app_fakes import FixedPriceSource


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    monkeypatch.setattr(main, "create_market_source", lambda cache: FixedPriceSource(cache))
    with TestClient(main.app) as test_client:
        yield test_client
