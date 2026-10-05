"""Unit tests for failure simulation endpoints (error and crash).

Validates error response codes, structured error payloads, and safe crash
simulation ensuring that the pytest test runner process is NEVER terminated.
"""

import time
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.api.simulate import reset_crash_executor, set_crash_executor
from app.config import get_settings


def test_simulate_error_default(client: TestClient) -> None:
    """Test POST /api/simulate/error returns HTTP 500 and structured error payload."""
    response = client.post("/api/simulate/error")
    assert response.status_code == 500

    data = response.json()
    assert data["error"] == "SimulatedApplicationError"
    assert data["error_code"] == "SIM_ERR_500"
    assert "Simulated internal server exception" in data["message"]
    assert "request_id" in data
    assert "timestamp" in data
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] == data["request_id"]


def test_simulate_error_custom_payload(client: TestClient) -> None:
    """Test POST /api/simulate/error with custom error details and error code."""
    payload = {
        "error_code": "CUSTOM_ALERT_TEST",
        "detail": "High-volume synthetic failure triggered for alert testing",
    }
    response = client.post("/api/simulate/error", json=payload)
    assert response.status_code == 500

    data = response.json()
    assert data["error"] == "SimulatedApplicationError"
    assert data["error_code"] == "CUSTOM_ALERT_TEST"
    assert data["message"] == "High-volume synthetic failure triggered for alert testing"
    assert "request_id" in data


def test_simulate_crash_safe_mode(client: TestClient) -> None:
    """Test POST /api/simulate/crash in safe test mode.

    The safety guard MUST be active and the pytest process MUST NOT be terminated.
    """
    settings = get_settings()
    # Confirm safety flags are active
    assert settings.ALLOW_PROCESS_TERMINATION is False or settings.TESTING is True

    payload = {"reason": "Pytest safety validation", "exit_code": 1}
    response = client.post("/api/simulate/crash", json=payload)

    # Must return HTTP 200 with safety guard status
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "simulated_crash_intercepted"
    assert data["terminated"] is False
    assert data["safety_guard"] == "active"
    assert data["exit_code"] == 1
    assert "Pytest safety validation" in data["reason"]


def test_simulate_crash_mocked_execution(client: TestClient) -> None:
    """Test crash simulation with a mock executor to verify termination logic.

    Ensures that when termination is enabled, the designated executor callback is called
    without invoking real os._exit, keeping pytest running safely.
    """
    settings = get_settings()
    original_allow = settings.ALLOW_PROCESS_TERMINATION
    original_testing = settings.TESTING

    mock_executor = MagicMock()
    set_crash_executor(mock_executor)

    try:
        # Temporarily enable termination flags with the mock executor
        settings.ALLOW_PROCESS_TERMINATION = True
        settings.TESTING = False

        payload = {"reason": "Testing supervisor restart hook", "exit_code": 42}
        response = client.post("/api/simulate/crash", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "simulated_crash_initiated"
        assert data["terminated"] is True
        assert data["safety_guard"] == "disabled"
        assert data["exit_code"] == 42

        # Allow background thread 100ms to fire the mock executor
        time.sleep(0.1)
        mock_executor.assert_called_once_with(42)
    finally:
        # Restore safety settings and real executor
        settings.ALLOW_PROCESS_TERMINATION = original_allow
        settings.TESTING = original_testing
        reset_crash_executor()
