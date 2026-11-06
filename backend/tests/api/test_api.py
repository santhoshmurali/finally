"""REST API contract: status codes, response shapes and error mapping.

The SSE stream is not exercised here: TestClient buffers streaming bodies, so
the stream is verified against a running uvicorn instead.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.market import DEFAULT_WATCHLIST
from tests.fakes import FakeSource

PRICES = {ticker: 100.0 + index for index, ticker in enumerate(DEFAULT_WATCHLIST)}
PRICES["WIPRO"] = 30.0


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        db_path=tmp_path / "finally.db",
        static_dir=tmp_path / "no-static",
        llm_mock=True,
        openrouter_api_key="",
    )
    app = create_app(settings, make_source=lambda cache: FakeSource(cache, PRICES))
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_source(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "market_source": "simulator",
        "market_source_healthy": True,
    }


def test_fresh_portfolio_has_starting_cash_and_no_positions(client):
    body = client.get("/api/portfolio").json()

    assert body["cash_balance"] == 1_000_000.0
    assert body["positions"] == []
    assert body["total_value"] == 1_000_000.0


def test_watchlist_lists_default_tickers_with_prices(client):
    entries = client.get("/api/watchlist").json()

    assert {entry["ticker"] for entry in entries} == set(DEFAULT_WATCHLIST)
    assert all(entry["price"] is not None for entry in entries)


def test_buy_then_sell_round_trip(client):
    bought = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 2, "side": "buy"}
    )
    assert bought.status_code == 200
    assert bought.json()["cash_balance"] == pytest.approx(1_000_000.0 - 2 * PRICES["TCS"])

    portfolio = client.get("/api/portfolio").json()
    assert [p["ticker"] for p in portfolio["positions"]] == ["TCS"]

    sold = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 2, "side": "sell"}
    )
    assert sold.status_code == 200
    assert client.get("/api/portfolio").json()["positions"] == []


def test_trade_with_insufficient_cash_returns_400_with_detail(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 1_000_000, "side": "buy"}
    )

    assert response.status_code == 400
    assert "insufficient cash" in response.json()["detail"]


def test_trade_on_unknown_ticker_returns_400(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "NOPE", "quantity": 1, "side": "buy"}
    )

    assert response.status_code == 400


def test_trade_with_unknown_side_returns_400(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 1, "side": "hold"}
    )

    assert response.status_code == 400


def test_history_starts_with_startup_snapshot(client):
    points = client.get("/api/portfolio/history").json()

    assert len(points) >= 1
    assert points[0]["total_value"] == pytest.approx(1_000_000.0)


def test_history_rejects_unknown_range(client):
    response = client.get("/api/portfolio/history", params={"range": "5y"})

    assert response.status_code == 400


def test_history_limit_must_be_positive(client):
    response = client.get("/api/portfolio/history", params={"limit": 0})

    assert response.status_code == 422


def test_watchlist_add_then_duplicate_then_remove(client):
    added = client.post("/api/watchlist", json={"ticker": "wipro"})
    assert added.status_code == 201
    assert added.json()["ticker"] == "WIPRO"

    assert client.post("/api/watchlist", json={"ticker": "WIPRO"}).status_code == 409

    assert client.delete("/api/watchlist/WIPRO").status_code == 204
    assert client.delete("/api/watchlist/WIPRO").status_code == 404


def test_watchlist_rejects_unsupported_and_malformed_tickers(client):
    assert client.post("/api/watchlist", json={"ticker": "NOPE"}).status_code == 400
    assert client.post("/api/watchlist", json={"ticker": "a b"}).status_code == 400


def test_watchlist_entries_are_listed_after_add(client):
    client.post("/api/watchlist", json={"ticker": "WIPRO"})

    tickers = [entry["ticker"] for entry in client.get("/api/watchlist").json()]

    assert "WIPRO" in tickers
