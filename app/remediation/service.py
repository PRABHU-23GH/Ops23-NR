"""Human-in-the-Loop Remediation Approval Service.

Phase 8: Manages approval lifecycle, safety enforcement, audit logging,
replay prevention, and execution dispatch to the Phase 6 remediation Lambda.
"""

from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import boto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.logger import logger as app_logger
from app.rca.service import ALLOWED_ACTION, ALLOWED_SERVICE, ALLOWED_TARGET
from app.remediation.models import (
    ApprovalRecord,
    ApprovalStatus,
    ApproveRequest,
    CreateApprovalRequest,
    ExecuteRemediationRequest,
    ExecutionStatus,
    RejectRequest,
)
from app.remediation.state_machine import assert_transition_allowed, validate_transition
from app.remediation.storage import ApprovalStorage

audit_logger = logging.getLogger("ops23.audit.remediation")


def emit_audit_event(event_name: str, payload: Dict[str, Any]) -> None:
    """Emits structured audit log entries without secret exposure."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # Filter out any sensitive keys if accidentally present
    sanitized = {
        k: v
        for k, v in payload.items()
        if not any(token in k.lower() for token in ["secret", "token", "key", "password", "auth"])
    }
    audit_data = {
        "event": event_name,
        "timestamp": now_iso,
        **sanitized,
    }
    audit_logger.info(json.dumps(audit_data))
    app_logger.info(f"AUDIT_EVENT [{event_name}]: {json.dumps(audit_data)}")


class RemediationApprovalService:
    """Core service for managing Human-in-the-Loop remediation approvals."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        storage: Optional[ApprovalStorage] = None,
        lambda_client: Any = None,
    ):
        self.settings = settings or get_settings()
        self.storage = storage or ApprovalStorage(
            table_name=self.settings.REMEDIATION_APPROVAL_TABLE_NAME,
            region_name=self.settings.AWS_REGION,
        )
        self._lambda_client = lambda_client

    @property
    def lambda_client(self) -> Any:
        if self._lambda_client is None:
            self._lambda_client = boto3.client("lambda", region_name=self.settings.AWS_REGION)
        return self._lambda_client

    def validate_safety_contract(self, request: CreateApprovalRequest) -> Tuple[bool, str]:
        """Validates that proposed recommendation strictly complies with Phase 7 allowlist."""
        action = request.recommended_action.strip()
        target = request.target.strip()
        service = request.service.strip()

        # Reject prohibited shell injection tokens
        dangerous_tokens = [";", "&&", "||", "|", "`", "$", "rm ", "sh ", "bash", "systemctl", "curl", "wget"]
        for field in (action, target, service):
            if any(token in field.lower() for token in dangerous_tokens):
                return False, "Prohibited shell metacharacters or dangerous commands detected."

        if action != ALLOWED_ACTION:
            return False, f"Action '{action}' is not allowlisted (expected '{ALLOWED_ACTION}')."

        if target != ALLOWED_TARGET:
            return False, f"Target '{target}' is unauthorized (expected '{ALLOWED_TARGET}')."

        if service != ALLOWED_SERVICE:
            return False, f"Service '{service}' is unauthorized (expected '{ALLOWED_SERVICE}')."

        if request.decision != "ALLOWLISTED_RECOMMENDATION":
            return False, f"RCA decision must be ALLOWLISTED_RECOMMENDATION (received '{request.decision}')."

        # Critical Safety Rule: Bedrock itself cannot execute
        if request.execution_allowed is not False:
            return False, "Safety validation failure: AI execution_allowed must be False."

        return True, "Safety contract verified."

    def create_approval(self, request: CreateApprovalRequest) -> ApprovalRecord:
        """Creates a pending remediation approval from a validated RCA recommendation."""
        is_safe, error_msg = self.validate_safety_contract(request)
        if not is_safe:
            emit_audit_event(
                "remediation_approval_creation_rejected",
                {
                    "incident_id": request.incident_id,
                    "action": request.recommended_action,
                    "target": request.target,
                    "service": request.service,
                    "reason": error_msg,
                },
            )
            raise ValueError(f"Safety Validation Rejected: {error_msg}")

        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
        ttl_seconds = self.settings.REMEDIATION_APPROVAL_TTL_SECONDS
        expires_ts = now_ts + ttl_seconds
        expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()

        approval_id = str(uuid.uuid4())
        event_id = request.event_id or f"approval-evt-{approval_id}"

        record = ApprovalRecord(
            approval_id=approval_id,
            incident_id=request.incident_id,
            event_id=event_id,
            service=request.service,
            target=request.target,
            recommended_action=request.recommended_action,
            root_cause=request.root_cause,
            confidence=request.confidence,
            decision=request.decision,
            approval_status=ApprovalStatus.PENDING,
            created_at=now.isoformat(),
            expires_at=expires_at,
            ttl=expires_ts,
            execution_status=ExecutionStatus.NOT_EXECUTED,
            evidence=request.evidence,
            reasoning_summary=request.reasoning_summary,
            metadata=request.metadata,
        )

        saved = self.storage.save_approval(record)
        if not saved:
            raise RuntimeError(f"Failed to persist approval {approval_id}: already exists or storage error.")

        emit_audit_event(
            "remediation_approval_created",
            {
                "approval_id": record.approval_id,
                "incident_id": record.incident_id,
                "action": record.recommended_action,
                "target": record.target,
                "service": record.service,
                "confidence": record.confidence,
                "expires_at": record.expires_at,
                "approval_status": record.approval_status.value,
            },
        )

        return record

    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        """Retrieves an approval record, automatically marking it EXPIRED if TTL has elapsed."""
        record = self.storage.get_approval(approval_id)
        if not record:
            return None

        # Check TTL expiration
        if record.is_expired() and record.approval_status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
            self.storage.transition_to_expired(approval_id)
            record.approval_status = ApprovalStatus.EXPIRED
            emit_audit_event(
                "remediation_approval_expired",
                {
                    "approval_id": record.approval_id,
                    "incident_id": record.incident_id,
                    "action": record.recommended_action,
                    "expired_at": record.expires_at,
                },
            )

        return record

    def approve_remediation(self, approval_id: str, request: ApproveRequest) -> ApprovalRecord:
        """Explicit human approval of a pending remediation."""
        record = self.get_approval(approval_id)
        if not record:
            raise KeyError(f"Remediation approval '{approval_id}' not found.")

        if record.is_expired() or record.approval_status == ApprovalStatus.EXPIRED:
            emit_audit_event(
                "remediation_approval_rejected",
                {
                    "approval_id": approval_id,
                    "incident_id": record.incident_id,
                    "reason": "Attempted to approve an expired recommendation.",
                },
            )
            raise ValueError(f"Approval '{approval_id}' has expired and cannot be approved.")

        # State machine check
        assert_transition_allowed(record.approval_status, ApprovalStatus.APPROVED)

        # Idempotent re-approval check
        if record.approval_status == ApprovalStatus.APPROVED:
            return record

        now_iso = datetime.now(timezone.utc).isoformat()
        success, updated_record, err = self.storage.transition_to_approved(
            approval_id=approval_id,
            approved_by=request.approved_by,
            approved_at=now_iso,
        )

        if not success or not updated_record:
            raise RuntimeError(f"Approval state transition failed: {err}")

        emit_audit_event(
            "remediation_approval_approved",
            {
                "approval_id": approval_id,
                "incident_id": updated_record.incident_id,
                "approved_by": request.approved_by,
                "action": updated_record.recommended_action,
                "target": updated_record.target,
                "service": updated_record.service,
                "confidence": updated_record.confidence,
                "timestamp": now_iso,
            },
        )

        return updated_record

    def reject_remediation(self, approval_id: str, request: RejectRequest) -> ApprovalRecord:
        """Rejects a pending remediation recommendation."""
        record = self.get_approval(approval_id)
        if not record:
            raise KeyError(f"Remediation approval '{approval_id}' not found.")

        if record.approval_status == ApprovalStatus.REJECTED:
            raise ValueError(f"Approval '{approval_id}' is already REJECTED.")

        if record.is_expired() or record.approval_status == ApprovalStatus.EXPIRED:
            raise ValueError(f"Approval '{approval_id}' has expired.")

        assert_transition_allowed(record.approval_status, ApprovalStatus.REJECTED)

        now_iso = datetime.now(timezone.utc).isoformat()
        success, updated_record, err = self.storage.transition_to_rejected(
            approval_id=approval_id,
            rejected_by=request.rejected_by,
            rejected_at=now_iso,
            reason=request.reason,
        )

        if not success or not updated_record:
            raise RuntimeError(f"Rejection state transition failed: {err}")

        emit_audit_event(
            "remediation_approval_rejected",
            {
                "approval_id": approval_id,
                "incident_id": updated_record.incident_id,
                "rejected_by": request.rejected_by,
                "reason": request.reason,
                "action": updated_record.recommended_action,
                "timestamp": now_iso,
            },
        )

        return updated_record

    def execute_remediation(self, approval_id: str, request: ExecuteRemediationRequest) -> ApprovalRecord:
        """Executes ONLY an already-approved remediation by invoking Phase 6 Lambda."""
        record = self.get_approval(approval_id)
        if not record:
            raise KeyError(f"Remediation approval '{approval_id}' not found.")

        if record.approval_status == ApprovalStatus.PENDING:
            raise ValueError("Remediation execution requires prior explicit human approval. Current state is PENDING.")

        if record.approval_status in (ApprovalStatus.EXECUTED, ApprovalStatus.EXECUTING):
            raise ValueError(f"Remediation already executed or currently executing (state={record.approval_status.value}). Replay prevented.")

        if record.is_expired() or record.approval_status == ApprovalStatus.EXPIRED:
            raise ValueError(f"Approval '{approval_id}' has expired and cannot be executed.")

        if record.approval_status != ApprovalStatus.APPROVED:
            raise ValueError(f"Remediation cannot be executed in state '{record.approval_status.value}'. Must be APPROVED.")

        # Verify allowlist on stored record once more to ensure no tamper
        if (
            record.recommended_action != ALLOWED_ACTION
            or record.target != ALLOWED_TARGET
            or record.service != ALLOWED_SERVICE
        ):
            raise ValueError("Stored approval violates deterministic safety allowlist.")

        # Atomic transition to EXECUTING (locks out concurrent execute requests)
        success, locked_record, err = self.storage.transition_to_executing(approval_id)
        if not success or not locked_record:
            raise RuntimeError(f"Concurrent execution lock failed: {err}")

        emit_audit_event(
            "remediation_execution_started",
            {
                "approval_id": approval_id,
                "incident_id": record.incident_id,
                "executed_by": request.executed_by,
                "action": record.recommended_action,
                "target": record.target,
                "service": record.service,
            },
        )

        # Build payload for existing Phase 6 Lambda
        lambda_payload = {
            "action": record.recommended_action,
            "target": record.target,
            "service": record.service,
            "event_id": record.event_id,
            "incident_id": record.incident_id,
            "condition_name": "Phase8HumanApprovedRemediation",
            "approved_by": record.approved_by,
        }

        try:
            lambda_response = self.lambda_client.invoke(
                FunctionName=self.settings.REMEDIATION_LAMBDA_NAME,
                InvocationType="RequestResponse",
                Payload=json.dumps(lambda_payload).encode("utf-8"),
            )

            response_status = lambda_response.get("StatusCode", 500)
            payload_stream = lambda_response.get("Payload")
            raw_result = payload_stream.read().decode("utf-8") if payload_stream else "{}"

            try:
                result_data = json.loads(raw_result)
            except Exception:
                result_data = {"raw_response": raw_result}

            # Check if Lambda returned HTTP 200 proxy response
            if response_status == 200:
                # If Lambda handler returned API Gateway format {"statusCode": 200, "body": "..."}
                inner_body = result_data
                if isinstance(result_data, dict) and "body" in result_data and isinstance(result_data["body"], str):
                    try:
                        inner_body = json.loads(result_data["body"])
                    except Exception:
                        inner_body = {"body": result_data["body"]}

                # Extract SSM Command ID if present
                ssm_cmd_id = (
                    inner_body.get("ssm_command_id")
                    if isinstance(inner_body, dict)
                    else None
                )

                # Record successful execution
                _, executed_record, _ = self.storage.transition_to_executed(
                    approval_id=approval_id,
                    execution_result=inner_body if isinstance(inner_body, dict) else {"result": inner_body},
                    ssm_command_id=ssm_cmd_id,
                )

                emit_audit_event(
                    "remediation_execution_completed",
                    {
                        "approval_id": approval_id,
                        "incident_id": record.incident_id,
                        "action": record.recommended_action,
                        "target": record.target,
                        "ssm_command_id": ssm_cmd_id,
                        "status": "SUCCESS",
                    },
                )
                return executed_record or locked_record

            else:
                err_msg = f"Remediation Lambda invocation failed with status {response_status}: {raw_result}"
                self.storage.transition_to_execution_failed(approval_id, err_msg, result_data)
                emit_audit_event(
                    "remediation_execution_failed",
                    {
                        "approval_id": approval_id,
                        "incident_id": record.incident_id,
                        "error": err_msg,
                    },
                )
                raise RuntimeError(err_msg)

        except Exception as e:
            err_msg = f"Execution error: {str(e)}"
            self.storage.transition_to_execution_failed(approval_id, err_msg)
            emit_audit_event(
                "remediation_execution_failed",
                {
                    "approval_id": approval_id,
                    "incident_id": record.incident_id,
                    "error": err_msg,
                },
            )
            raise
