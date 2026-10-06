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
    ReconcileRequest,
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
        ssm_client: Any = None,
    ):
        self.settings = settings or get_settings()
        self.storage = storage or ApprovalStorage(
            table_name=self.settings.REMEDIATION_APPROVAL_TABLE_NAME,
            region_name=getattr(self.settings, "AWS_REGION", "ap-south-1"),
        )
        self._lambda_client = lambda_client
        self._ssm_client = ssm_client

    @property
    def lambda_client(self) -> Any:
        if self._lambda_client is None:
            region = getattr(self.settings, "AWS_REGION", "ap-south-1")
            self._lambda_client = boto3.client("lambda", region_name=region)
        return self._lambda_client

    @property
    def ssm_client(self) -> Any:
        if self._ssm_client is None:
            region = getattr(self.settings, "AWS_REGION", "ap-south-1")
            self._ssm_client = boto3.client("ssm", region_name=region)
        return self._ssm_client

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
        exec_start_iso = datetime.now(timezone.utc).isoformat()
        success, locked_record, err = self.storage.transition_to_executing(
            approval_id=approval_id,
            execution_started_at=exec_start_iso,
        )
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
                "execution_started_at": exec_start_iso,
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

                completed_iso = datetime.now(timezone.utc).isoformat()
                # Record successful execution
                _, executed_record, _ = self.storage.transition_to_executed(
                    approval_id=approval_id,
                    execution_result=inner_body if isinstance(inner_body, dict) else {"result": inner_body},
                    ssm_command_id=ssm_cmd_id,
                    execution_completed_at=completed_iso,
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
                        "execution_completed_at": completed_iso,
                    },
                )
                return executed_record or locked_record

            else:
                completed_iso = datetime.now(timezone.utc).isoformat()
                err_msg = f"Remediation Lambda invocation failed with status {response_status}: {raw_result}"
                self.storage.transition_to_execution_failed(
                    approval_id,
                    err_msg,
                    result_data,
                    execution_completed_at=completed_iso,
                )
                emit_audit_event(
                    "remediation_execution_failed",
                    {
                        "approval_id": approval_id,
                        "incident_id": record.incident_id,
                        "error": err_msg,
                        "execution_completed_at": completed_iso,
                    },
                )
                raise RuntimeError(err_msg)

        except Exception as e:
            completed_iso = datetime.now(timezone.utc).isoformat()
            err_msg = f"Execution error: {str(e)}"
            self.storage.transition_to_execution_failed(
                approval_id,
                err_msg,
                execution_completed_at=completed_iso,
            )
            emit_audit_event(
                "remediation_execution_failed",
                {
                    "approval_id": approval_id,
                    "incident_id": record.incident_id,
                    "error": err_msg,
                    "execution_completed_at": completed_iso,
                },
            )
            raise

    def check_application_health(self, health_url: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """Performs a non-invasive GET to verify application health status.
        
        Returns (is_healthy, details).
        """
        import urllib.request
        target_url = health_url or getattr(self.settings, "HEALTH_CHECK_URL", "http://127.0.0.1:8000/health")
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": "Ops23-Reconciler"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                status_code = resp.getcode()
                raw_data = resp.read().decode("utf-8")
                try:
                    body = json.loads(raw_data)
                except Exception:
                    body = {"raw": raw_data}
                is_healthy = status_code == 200
                return is_healthy, {"status_code": status_code, "body": body}
        except Exception as err:
            return False, {"error": str(err)}

    def reconcile_execution(
        self,
        approval_id: str,
        request: Optional[ReconcileRequest] = None,
        health_checker: Optional[Any] = None,
    ) -> ApprovalRecord:
        """Safely reconciles an existing EXECUTING approval against observed SSM and health evidence.
        
        SAFETY GUARANTEES:
        - NEVER dispatches a new SSM command (read-only get_command_invocation / list_command_invocations only).
        - NEVER invokes the remediation Lambda.
        - NEVER restarts the service or runs shell commands.
        - NEVER bypasses approval or modifies unapproved records.
        - NEVER weakens replay protection.
        """
        record = self.storage.get_approval(approval_id)
        if not record:
            raise KeyError(f"Remediation approval '{approval_id}' not found.")

        reconciler = (request.reconciled_by if request else "system") or "system"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Idempotency: if already in a terminal state, return safely
        if record.approval_status == ApprovalStatus.EXECUTED:
            return record

        if record.approval_status == ApprovalStatus.EXECUTION_FAILED:
            return record

        # Strict state validation: only EXECUTING records can be reconciled
        if record.approval_status != ApprovalStatus.EXECUTING:
            raise ValueError(
                f"Cannot reconcile approval '{approval_id}': status is {record.approval_status.value} (must be EXECUTING)."
            )

        emit_audit_event(
            "remediation_reconciliation_started",
            {
                "approval_id": approval_id,
                "incident_id": record.incident_id,
                "target": record.target,
                "reconciled_by": reconciler,
                "timestamp": now_iso,
            },
        )

        # 1. Determine candidate SSM Command ID
        candidate_cmd_id = None
        if request and request.ssm_command_id:
            candidate_cmd_id = request.ssm_command_id.strip()
        elif record.ssm_command_id and record.ssm_command_id != "NONE":
            candidate_cmd_id = record.ssm_command_id.strip()

        # If not known, query SSM for recent command invocations on target instance
        if not candidate_cmd_id:
            try:
                invocations_resp = self.ssm_client.list_command_invocations(
                    InstanceId=record.target,
                    MaxResults=10,
                    Details=True,
                )
                invocations = invocations_resp.get("CommandInvocations", [])
                for inv in invocations:
                    doc_name = inv.get("DocumentName", "")
                    if doc_name == "AWS-RunShellScript":
                        candidate_cmd_id = inv.get("CommandId")
                        break
            except Exception as ssm_lookup_err:
                app_logger.warning(f"Could not list SSM command invocations for {record.target}: {ssm_lookup_err}")

        # 2. Query SSM invocation status if command ID is available
        ssm_status = "UNKNOWN"
        ssm_details = {}
        if candidate_cmd_id:
            try:
                inv_resp = self.ssm_client.get_command_invocation(
                    CommandId=candidate_cmd_id,
                    InstanceId=record.target,
                )
                ssm_status = inv_resp.get("Status", "UNKNOWN")
                ssm_details = {
                    "command_id": candidate_cmd_id,
                    "status": ssm_status,
                    "response_code": inv_resp.get("ResponseCode"),
                    "status_details": inv_resp.get("StatusDetails"),
                    "execution_start_time": str(inv_resp.get("ExecutionStartDateTime", "")),
                    "execution_end_time": str(inv_resp.get("ExecutionEndDateTime", "")),
                }
            except Exception as ssm_get_err:
                ssm_details = {"command_id": candidate_cmd_id, "error": str(ssm_get_err)}
                app_logger.warning(f"Error querying SSM command {candidate_cmd_id}: {ssm_get_err}")

        # 3. Verify application health
        if health_checker:
            is_healthy, health_info = health_checker()
        else:
            is_healthy, health_info = self.check_application_health()

        evidence = {
            "ssm_command_id": candidate_cmd_id,
            "ssm_status": ssm_status,
            "ssm_details": ssm_details,
            "health_status": "healthy" if is_healthy else "unhealthy",
            "health_info": health_info,
            "observed_at": now_iso,
        }

        # 4. State transition based on verified evidence
        if ssm_status == "Success" and is_healthy:
            exec_result = {
                "reconciled": True,
                "ssm_command_id": candidate_cmd_id,
                "ssm_status": ssm_status,
                "health_verification": health_info,
            }
            success, updated_record, err = self.storage.transition_to_reconciled_executed(
                approval_id=approval_id,
                ssm_command_id=candidate_cmd_id,
                execution_result=exec_result,
                reconciled_by=reconciler,
                reconciled_at=now_iso,
                evidence=evidence,
            )
            if not success or not updated_record:
                raise RuntimeError(f"Failed to transition to reconciled EXECUTED: {err}")

            emit_audit_event(
                "remediation_reconciliation_completed",
                {
                    "approval_id": approval_id,
                    "incident_id": record.incident_id,
                    "ssm_command_id": candidate_cmd_id,
                    "execution_status": "EXECUTED",
                    "health_status": "healthy",
                    "reconciled_by": reconciler,
                    "timestamp": now_iso,
                },
            )
            return updated_record

        elif ssm_status in ("Failed", "Cancelled", "TimedOut"):
            err_msg = f"Observed SSM execution terminal failure: status={ssm_status}"
            success, updated_record, err = self.storage.transition_to_reconciled_failed(
                approval_id=approval_id,
                error_message=err_msg,
                ssm_command_id=candidate_cmd_id,
                reconciled_by=reconciler,
                reconciled_at=now_iso,
                evidence=evidence,
            )
            if not success or not updated_record:
                raise RuntimeError(f"Failed to transition to reconciled EXECUTION_FAILED: {err}")

            emit_audit_event(
                "remediation_reconciliation_failed",
                {
                    "approval_id": approval_id,
                    "incident_id": record.incident_id,
                    "ssm_command_id": candidate_cmd_id,
                    "error": err_msg,
                    "reconciled_by": reconciler,
                    "timestamp": now_iso,
                },
            )
            return updated_record

        else:
            # Command still InProgress, Pending, Delayed, or missing command ID / health evidence insufficient
            app_logger.info(
                f"Reconciliation for approval {approval_id} remains EXECUTING. "
                f"SSM status='{ssm_status}', is_healthy={is_healthy}"
            )
            return record
