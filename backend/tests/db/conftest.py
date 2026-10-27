"""Fixtures that point the database at a temporary file."""

import pytest

from db.connection import init_db


@pytest.fixture
def initialized_db(tmp_path, monkeypatch):
    """Fresh, seeded database file for one test."""
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    init_db()
