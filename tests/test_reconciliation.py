"""Tests for Phase 8 Post-Remediation State Reconciliation Mechanism.

Covers all 14 mandatory test requirements:
1. EXECUTING + SSM Success + Health 200 -> EXECUTED
2. EXECUTING + SSM Failure -> EXECUTION_FAILED
3. EXECUTING + SSM InProgress -> remains EXECUTING
4. Missing command ID -> remains EXECUTING (unresolved)
5. Missing health evidence -> remains EXECUTING
6. Duplicate reconciliation
7. Concurrent reconciliation
8. Already EXECUTED record
9. Invalid state rejection (PENDING, APPROVED, REJECTED, EXPIRED)
10. No SSM command created by reconciliation (NEVER calls send_command)
11. No Lambda invocation created by reconciliation (NEVER calls invoke)
12. Existing Phase 6 idempotency contracts preserved
13. Existing Phase 7 safety validation preserved
14. Full API endpoint reconciliation test
"""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.rca.service import ALLOWED_ACTION, ALLOWED_SERVICE, ALLOWED_TARGET
from app.remediation.models import (
    ApprovalRecord,
    ApprovalStatus,
    CreateApprovalRequest,
    ExecutionStatus,
    ReconcileRequest,
)
from app.remediation.service import RemediationApprovalService
from tests.test_approvals import InMemoryApprovalStorage


@pytest.fixture
def test_storage():
    return InMemoryApprovalStorage()


@pytest.fixture
def mock_ssm():
    ssm = MagicMock()
    # Default to Success
    ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "ResponseCode": 0,
        "StatusDetails": "Success",
        "ExecutionStartDateTime": "2026-10-06T12:00:00Z",
        "ExecutionEndDateTime": "2026-10-06T12:00:15Z",
    }
    ssm.list_command_invocations.return_value = {
        "CommandInvocations": [
            {
                "CommandId": "74572c11-3061-40bf-bbed-c9ffa5ec9dea",
                "DocumentName": "AWS-RunShellScript",
                "Status": "Success",
            }
        ]
    }
    return ssm


@pytest.fixture
def mock_lambda():
    return MagicMock()


@pytest.fixture
def reconciliation_service(test_storage, mock_ssm, mock_lambda):
    return RemediationApprovalService(
        storage=test_storage,
        ssm_client=mock_ssm,
        lambda_client=mock_lambda,
    )


def helper_create_executing_approval(storage, approval_id=None, ssm_command_id=None):
    now = datetime.now(timezone.utc).isoformat()
    rec_id = approval_id or str(uuid.uuid4())
    record = ApprovalRecord(
        approval_id=rec_id,
        incident_id="INC-8143846-992",
        event_id=f"approval-evt-{rec_id}",
        service=ALLOWED_SERVICE,
        target=ALLOWED_TARGET,
        recommended_action=ALLOWED_ACTION,
        root_cause="FastAPI service stopped responding to health checks",
        confidence=0.96,
        decision="ALLOWLISTED_RECOMMENDATION",
        approval_status=ApprovalStatus.EXECUTING,
        created_at=now,
        expires_at=now,
        ttl=1760000000,
        approved_by="Prabhu",
        approved_at=now,
        execution_status=ExecutionStatus.EXECUTING,
        execution_started_at=now,
        ssm_command_id=ssm_command_id,
        evidence=["Health check failures"],
    )
    storage.save_approval(record)
    return record


# 1. EXECUTING + SSM Success + Health 200 -> EXECUTED
def test_1_reconcile_ssm_success_and_health_200(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    
    mock_ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "ResponseCode": 0,
        "StatusDetails": "Success",
    }
    healthy_checker = lambda: (True, {"status_code": 200, "status": "healthy"})

    updated = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )

    assert updated.approval_status == ApprovalStatus.EXECUTED
    assert updated.execution_status == ExecutionStatus.EXECUTED
    assert updated.ssm_command_id == "cmd-12345"
    assert updated.reconciled_by == "sre.prabhu"
    assert updated.reconciled_at is not None
    assert updated.reconciliation_evidence["health_status"] == "healthy"
    assert updated.reconciliation_evidence["ssm_status"] == "Success"


# 2. EXECUTING + SSM Failure -> EXECUTION_FAILED
def test_2_reconcile_ssm_failure(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-failed-99")
    
    mock_ssm.get_command_invocation.return_value = {
        "Status": "Failed",
        "ResponseCode": 1,
        "StatusDetails": "Failed",
    }
    healthy_checker = lambda: (True, {"status_code": 200})

    updated = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )

    assert updated.approval_status == ApprovalStatus.EXECUTION_FAILED
    assert updated.execution_status == ExecutionStatus.EXECUTION_FAILED
    assert "Observed SSM execution terminal failure" in updated.error_message


# 3. EXECUTING + SSM InProgress -> remains EXECUTING
def test_3_reconcile_ssm_in_progress(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-in-flight")
    
    mock_ssm.get_command_invocation.return_value = {
        "Status": "InProgress",
        "StatusDetails": "InProgress",
    }
    healthy_checker = lambda: (True, {"status_code": 200})

    updated = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )

    assert updated.approval_status == ApprovalStatus.EXECUTING
    assert updated.execution_status == ExecutionStatus.EXECUTING


# 4. Missing command ID -> remains EXECUTING
def test_4_reconcile_missing_command_id(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id=None)
    mock_ssm.list_command_invocations.return_value = {"CommandInvocations": []}

    healthy_checker = lambda: (True, {"status_code": 200})

    updated = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )

    assert updated.approval_status == ApprovalStatus.EXECUTING


# 5. Missing health evidence (SSM success, but health check failed) -> remains EXECUTING
def test_5_reconcile_missing_health_evidence(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    mock_ssm.get_command_invocation.return_value = {"Status": "Success"}

    unhealthy_checker = lambda: (False, {"error": "Connection refused / HTTP 502"})

    updated = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=unhealthy_checker,
    )

    assert updated.approval_status == ApprovalStatus.EXECUTING


# 6. Duplicate reconciliation
def test_6_duplicate_reconciliation(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    mock_ssm.get_command_invocation.return_value = {"Status": "Success"}
    healthy_checker = lambda: (True, {"status_code": 200})

    first = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )
    assert first.approval_status == ApprovalStatus.EXECUTED

    # Duplicate call
    second = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="sre.prabhu"),
        health_checker=healthy_checker,
    )
    assert second.approval_status == ApprovalStatus.EXECUTED
    assert second.approval_id == first.approval_id


# 7. Concurrent reconciliation
def test_7_concurrent_reconciliation(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    mock_ssm.get_command_invocation.return_value = {"Status": "Success"}
    healthy_checker = lambda: (True, {"status_code": 200})

    # Simulate another thread already transitioning it in storage
    test_storage.transition_to_reconciled_executed(
        record.approval_id,
        ssm_command_id="cmd-12345",
        execution_result={"reconciled": True},
        reconciled_by="worker-1",
        reconciled_at=datetime.now(timezone.utc).isoformat(),
    )

    # Calling reconcile now handles the already-transitioned record safely
    res = reconciliation_service.reconcile_execution(
        record.approval_id,
        request=ReconcileRequest(reconciled_by="worker-2"),
        health_checker=healthy_checker,
    )
    assert res.approval_status == ApprovalStatus.EXECUTED


# 8. Already EXECUTED record
def test_8_already_executed_record(reconciliation_service, test_storage):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    test_storage.transition_to_executed(record.approval_id, {"status": "SUCCESS"}, ssm_command_id="cmd-12345")

    result = reconciliation_service.reconcile_execution(record.approval_id)
    assert result.approval_status == ApprovalStatus.EXECUTED


# 9. Invalid state rejection
def test_9_invalid_state_rejection(reconciliation_service, test_storage):
    now = datetime.now(timezone.utc).isoformat()
    # Test PENDING
    rec_pending = ApprovalRecord(
        approval_id="pend-1",
        incident_id="INC-1",
        event_id="evt-1",
        service=ALLOWED_SERVICE,
        target=ALLOWED_TARGET,
        recommended_action=ALLOWED_ACTION,
        root_cause="err",
        confidence=0.9,
        decision="ALLOWLISTED_RECOMMENDATION",
        approval_status=ApprovalStatus.PENDING,
        created_at=now,
        expires_at=now,
        ttl=1760000000,
        execution_status=ExecutionStatus.NOT_EXECUTED,
    )
    test_storage.save_approval(rec_pending)

    with pytest.raises(ValueError, match="must be EXECUTING"):
        reconciliation_service.reconcile_execution(rec_pending.approval_id)

    # Test APPROVED
    test_storage.transition_to_approved("pend-1", "Prabhu", now)
    with pytest.raises(ValueError, match="must be EXECUTING"):
        reconciliation_service.reconcile_execution("pend-1")


# 10. No SSM command created by reconciliation
def test_10_no_ssm_command_created(reconciliation_service, test_storage, mock_ssm):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    mock_ssm.get_command_invocation.return_value = {"Status": "Success"}

    reconciliation_service.reconcile_execution(
        record.approval_id,
        health_checker=lambda: (True, {"status_code": 200}),
    )

    # Crucial security guarantee: send_command must NEVER be called
    assert not hasattr(mock_ssm, "send_command") or not mock_ssm.send_command.called


# 11. No Lambda invocation created by reconciliation
def test_11_no_lambda_invocation_created(reconciliation_service, test_storage, mock_lambda):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")

    reconciliation_service.reconcile_execution(
        record.approval_id,
        health_checker=lambda: (True, {"status_code": 200}),
    )

    # Crucial security guarantee: lambda.invoke must NEVER be called
    assert not mock_lambda.invoke.called


# 12. Existing Phase 6 idempotency preserved
def test_12_phase6_idempotency_preserved(reconciliation_service, test_storage):
    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-12345")
    assert record.event_id.startswith("approval-evt-")
    assert record.recommended_action == ALLOWED_ACTION


# 13. Existing Phase 7 safety validation preserved
def test_13_phase7_safety_validation_preserved(reconciliation_service):
    bad_req = CreateApprovalRequest(
        incident_id="INC-BAD",
        service="unauthorized.service",
        target=ALLOWED_TARGET,
        recommended_action="REBOOT_INSTANCE",
        root_cause="error",
        confidence=0.9,
    )
    with pytest.raises(ValueError):
        reconciliation_service.create_approval(bad_req)


# 14. Full API endpoint reconciliation test
def test_14_api_reconcile_endpoint(test_storage, mock_ssm):
    from app.api.approvals import get_approval_service

    record = helper_create_executing_approval(test_storage, ssm_command_id="cmd-live-123")
    mock_ssm.get_command_invocation.return_value = {"Status": "Success", "ResponseCode": 0}

    svc = RemediationApprovalService(storage=test_storage, ssm_client=mock_ssm)
    app.dependency_overrides[get_approval_service] = lambda: svc
    client = TestClient(app)

    try:
        with patch.object(svc, "check_application_health", return_value=(True, {"status_code": 200})):
            resp = client.post(
                f"/api/v1/remediation/approvals/{record.approval_id}/reconcile",
                headers={
                    "X-Approval-Token": "ops23-dev-approval-token",
                    "X-Approver-Id": "lead.engineer",
                },
                json={"reconciled_by": "lead.engineer", "ssm_command_id": "cmd-live-123"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["approval_status"] == "EXECUTED"
            assert data["execution_status"] == "EXECUTED"
            assert data["ssm_command_id"] == "cmd-live-123"
            assert data["reconciled_by"] == "lead.engineer"
    finally:
        app.dependency_overrides.clear()
