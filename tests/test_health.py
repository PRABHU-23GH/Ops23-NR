"""Unit tests for GET /health endpoint."""

from fastapi.testclient import TestClient


def test_get_health_success(client: TestClient) -> None:
    """Test GET /health returns status 200 and required lightweight fields."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Ops23-NR"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data

    # Verify x-request-id correlation header is present
    assert "x-request-id" in response.headers
