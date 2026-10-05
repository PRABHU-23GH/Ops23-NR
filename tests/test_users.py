"""Unit tests for GET /api/users endpoint."""

from fastapi.testclient import TestClient


def test_get_users_list(client: TestClient) -> None:
    """Test GET /api/users returns users list with schema validation."""
    response = client.get("/api/users")
    assert response.status_code == 200

    data = response.json()
    assert "total" in data
    assert "users" in data
    assert data["total"] > 0
    assert len(data["users"]) == data["total"]

    first_user = data["users"][0]
    assert "id" in first_user
    assert "name" in first_user
    assert "email" in first_user
    assert "role" in first_user
    assert "status" in first_user
    assert "created_at" in first_user
