"""Health endpoint body and status."""


def test_health_reports_status_source_and_market_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "market_source": "simulator",
        "market_healthy": True,
    }
