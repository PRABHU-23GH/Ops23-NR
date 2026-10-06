"""Tests for Ops23-NR Intelligent Cloud Operations Center Dashboard.

Phase 9: Validates HTML dashboard rendering and aggregated telemetry overview API.
"""

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_html_rendering(client):
    """Verifies that GET /dashboard renders HTML page with all key UI sections."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text

    # Verify key wireframe elements from the specification
    assert "OPS23-NR" in html
    assert "Intelligent Cloud Operations Center" in html
    assert "SYSTEM HEALTHY" in html
    assert "CPU" in html
    assert "Memory" in html
    assert "Requests" in html
    assert "Error Rate" in html
    assert "Incidents" in html
    assert "Service Health" in html
    assert "AI Root Cause Analysis" in html
    assert "FastAPI service stopped responding to health checks" in html
    assert "RESTART_OPS23_SERVICE" in html
    assert "Remediation Timeline" in html
    assert "Incident detected" in html
    assert "AI RCA completed" in html
    assert "btn-approve" in html
    assert "btn-reject" in html
    assert "btn-execute" in html


def test_dashboard_overview_api(client):
    """Verifies that GET /api/v1/dashboard/overview returns aggregated telemetry."""
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    data = response.json()

    assert "telemetry" in data
    assert "cpu_percent" in data["telemetry"]
    assert "memory_percent" in data["telemetry"]
    assert "requests_per_min" in data["telemetry"]
    assert "error_rate_percent" in data["telemetry"]

    assert "services" in data
    assert len(data["services"]) >= 4
    service_names = [s["name"] for s in data["services"]]
    assert "API" in service_names
    assert "Database" in service_names
    assert "EC2" in service_names
    assert "SSM" in service_names

    assert "sample_rca" in data
    assert data["sample_rca"]["recommended_action"] == "RESTART_OPS23_SERVICE"
    assert data["sample_rca"]["confidence"] == 0.96

    assert "timeline" in data
    assert len(data["timeline"]) == 5

    # Verify Step 1 required approval and remediation fields
    assert "approval_id" in data
    assert "approval_status" in data
    assert "execution_status" in data
    assert "recommended_action" in data
    assert "target" in data
    assert "approved_by" in data
    assert data["recommended_action"] == "RESTART_OPS23_SERVICE"
    assert data["target"] == "i-066478e6fd6dc22af"
    assert data["approved_by"] is not None


def test_dashboard_frontend_state_synchronization_contract(client):
    """Verifies that the dashboard HTML contains the strict 6-state frontend synchronization rules."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text

    # Verify existence of core state machine function and functions
    assert "function applyOperationalState(approvalStatus)" in html
    assert "async function refetchApprovalRecord()" in html
    assert "function handleExecutingPolling(status)" in html

    # Verify all 6 operational states are explicitly handled
    states = ["PENDING", "APPROVED", "EXECUTING", "EXECUTED", "REJECTED", "EXPIRED"]
    for s in states:
        assert s in html

    # State 1: PENDING -> Approve enabled, Execute disabled
    assert "approvalStatus === 'PENDING'" in html
    assert "btnApprove.disabled = false" in html
    assert "btnExecute.disabled = true" in html

    # State 2: APPROVED -> Approve disabled, Execute enabled
    assert "approvalStatus === 'APPROVED'" in html
    assert "btnApprove.disabled = true" in html
    assert "btnExecute.disabled = false" in html

    # State 3: EXECUTING -> Approve disabled, Execute disabled, label "EXECUTING..."
    assert "approvalStatus === 'EXECUTING'" in html
    assert "btnExecute.innerText = 'EXECUTING...'" in html

    # State 4: EXECUTED -> Approve disabled, Execute disabled, label "EXECUTED ✓"
    assert "approvalStatus === 'EXECUTED'" in html
    assert "btnExecute.innerText = 'EXECUTED ✓'" in html

    # State 5: REJECTED -> Approve disabled, Execute disabled
    assert "approvalStatus === 'REJECTED'" in html

    # State 6: EXPIRED -> Approve disabled, Execute disabled
    assert "approvalStatus === 'EXPIRED'" in html

    # Verify Step 6 refetching after actions:
    # After handleApprove -> refetchApprovalRecord() in finally block
    assert "async function handleApprove()" in html
    # After handleExecute -> refetchApprovalRecord() in finally block and handleExecutingPolling
    assert "async function handleExecute()" in html
    # Refetch in periodic initDashboard
    assert "setInterval(initDashboard, 10000)" in html

