"""Portfolio routes: trade execution, portfolio shape, errors and history."""


def test_empty_portfolio_has_starting_cash(client):
    response = client.get("/api/portfolio")

    assert response.status_code == 200
    assert response.json() == {
        "cash_balance": 1_000_000.0,
        "total_value": 1_000_000.0,
        "unrealized_pnl": 0.0,
        "positions": [],
    }


def test_buy_returns_the_trade_and_the_new_portfolio(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "tcs", "quantity": 10, "side": "buy"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["trade"]["ticker"] == "TCS"
    assert body["trade"]["price"] == 2500.0
    assert body["portfolio"]["cash_balance"] == 975_000.0
    assert body["portfolio"]["positions"][0]["avg_cost"] == 2500.0


def test_buy_beyond_cash_is_400(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 1000, "side": "buy"}
    )

    assert response.status_code == 400
    assert "Insufficient cash" in response.json()["detail"]


def test_sell_more_than_held_is_400(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 1, "side": "sell"}
    )

    assert response.status_code == 400
    assert "Insufficient shares" in response.json()["detail"]


def test_ticker_without_a_price_is_503(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "SILENT", "quantity": 1, "side": "buy"}
    )

    assert response.status_code == 503
    assert "No price yet" in response.json()["detail"]


def test_zero_quantity_is_422(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "TCS", "quantity": 0, "side": "buy"}
    )

    assert response.status_code == 422


def test_history_has_startup_and_trade_snapshots_and_honours_limit(client):
    client.post("/api/portfolio/trade", json={"ticker": "TCS", "quantity": 1, "side": "buy"})

    everything = client.get("/api/portfolio/history").json()
    newest = client.get("/api/portfolio/history", params={"limit": 1}).json()

    assert len(everything) == 2
    assert all(set(row) == {"total_value", "recorded_at"} for row in everything)
    assert newest == everything[-1:]
