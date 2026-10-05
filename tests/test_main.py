"""Unit tests for root endpoint and global middleware."""

from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient) -> None:
    """Test GET / returns valid service metadata and HTTP 200."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert data["service"] == "Ops23-NR"
    assert "Ops23-NR" in data["title"]
    assert data["status"] == "running"
    assert "version" in data
    assert "docs_url" in data


def test_request_id_middleware(client: TestClient) -> None:
    """Test that every response includes an x-request-id correlation header."""
    # When no header is supplied, a UUID is generated
    resp = client.get("/")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) > 0

    # When header is supplied, it is preserved
    custom_id = "test-custom-req-id-12345"
    resp2 = client.get("/", headers={"x-request-id": custom_id})
    assert resp2.status_code == 200
    assert resp2.headers["x-request-id"] == custom_id
