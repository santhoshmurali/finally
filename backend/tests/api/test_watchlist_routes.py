"""Watchlist routes: shapes and status codes."""

from app.market import DEFAULT_WATCHLIST
from tests.app_fakes import PRICES


def test_get_lists_the_default_tickers_with_prices(client):
    rows = client.get("/api/watchlist").json()

    assert [row["ticker"] for row in rows] == list(DEFAULT_WATCHLIST)
    assert all(row["price"] == PRICES[row["ticker"]] for row in rows)
    assert {"added_at", "previous_close", "day_change_percent"} <= set(rows[0])


def test_post_adds_a_ticker_with_201(client):
    response = client.post("/api/watchlist", json={"ticker": "wipro"})

    assert response.status_code == 201
    assert response.json()["ticker"] == "WIPRO"
    assert "added_at" in response.json()


def test_post_duplicate_is_400(client):
    response = client.post("/api/watchlist", json={"ticker": "TCS"})

    assert response.status_code == 400
    assert "already on the watchlist" in response.json()["detail"]


def test_post_unsupported_ticker_is_400(client):
    response = client.post("/api/watchlist", json={"ticker": "NOPE"})

    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_delete_removes_with_204_then_404(client):
    assert client.delete("/api/watchlist/TCS").status_code == 204

    response = client.delete("/api/watchlist/TCS")

    assert response.status_code == 404
    assert response.json() == {"detail": "TCS is not on the watchlist"}
