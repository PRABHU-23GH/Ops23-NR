"""Unit tests for GET /api/orders endpoint."""

from fastapi.testclient import TestClient


def test_get_orders_list(client: TestClient) -> None:
    """Test GET /api/orders returns orders list with schema validation."""
    response = client.get("/api/orders")
    assert response.status_code == 200

    data = response.json()
    assert "total" in data
    assert "orders" in data
    assert data["total"] > 0
    assert len(data["orders"]) == data["total"]

    first_order = data["orders"][0]
    assert "id" in first_order
    assert "user_id" in first_order
    assert "amount" in first_order
    assert "currency" in first_order
    assert "status" in first_order
    assert "items_count" in first_order
    assert "created_at" in first_order
