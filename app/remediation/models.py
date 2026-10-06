"""Approval Data Models for Human-in-the-Loop AI Remediation.

Phase 8: Approval requests, audit records, state models, and safety contracts.
"""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ApprovalStatus(str, Enum):
    """Strict lifecycle states for remediation approvals."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ExecutionStatus(str, Enum):
    """Execution progress status."""
    NOT_EXECUTED = "NOT_EXECUTED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


def validate_human_identity(name: str) -> str:
    """Ensures identity is provided and strictly not an autonomous/AI identity."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Approver identity cannot be empty.")
    
    # Strictly forbid AI / Bedrock / autonomous bots
    prohibited_patterns = [r"^ai$", r"^bedrock", r"^claude", r"^bot", r"^autonomous", r"^system$"]
    for pattern in prohibited_patterns:
        if re.search(pattern, cleaned, re.IGNORECASE):
            raise ValueError(f"Identity '{cleaned}' is not a valid human approver. Autonomous/AI approval is strictly prohibited.")
    
    return cleaned


class CreateApprovalRequest(BaseModel):
    """Payload to create a pending remediation approval from RCA."""
    incident_id: str = Field(..., min_length=1, description="Correlated incident ID")
    event_id: Optional[str] = Field(default=None, description="Optional unique event ID")
    service: str = Field(..., description="Target service identifier (e.g. ops23-nr.service)")
    target: str = Field(..., description="Target EC2 instance ID (e.g. i-066478e6fd6dc22af)")
    recommended_action: str = Field(..., description="Action to be approved (e.g. RESTART_OPS23_SERVICE)")
    root_cause: str = Field(..., min_length=1, description="Root cause diagnosis from RCA")
    confidence: float = Field(..., ge=0.0, le=1.0, description="RCA confidence score")
    decision: str = Field(default="ALLOWLISTED_RECOMMENDATION", description="Validation decision from Phase 7 validator")
    execution_allowed: bool = Field(default=False, description="Must be False; Bedrock cannot execute directly")
    evidence: List[str] = Field(default_factory=list, description="Diagnostic evidence points")
    reasoning_summary: Optional[str] = Field(default=None, description="Analytical reasoning summary from RCA")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata")

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(v, 4)


class ApproveRequest(BaseModel):
    """Payload to approve a pending remediation recommendation."""
    approved_by: str = Field(..., min_length=1, description="Human approver username or identifier")
    notes: Optional[str] = Field(default=None, description="Optional approval notes or justification")

    @field_validator("approved_by")
    @classmethod
    def check_human(cls, v: str) -> str:
        return validate_human_identity(v)


class RejectRequest(BaseModel):
    """Payload to reject a pending remediation recommendation."""
    rejected_by: str = Field(..., min_length=1, description="Human rejector username or identifier")
    reason: str = Field(..., min_length=1, description="Reason for rejection")

    @field_validator("rejected_by")
    @classmethod
    def check_human(cls, v: str) -> str:
        return validate_human_identity(v)


class ExecuteRemediationRequest(BaseModel):
    """Request to execute an approved remediation.
    
    IMPORTANT: Caller CANNOT specify arbitrary action, target, or command.
    The service strictly reads the stored, verified approval record.
    """
    executed_by: str = Field(..., min_length=1, description="Human operator initiating execution")

    @field_validator("executed_by")
    @classmethod
    def check_human(cls, v: str) -> str:
        return validate_human_identity(v)


class ReconcileRequest(BaseModel):
    """Payload to safely reconcile an existing EXECUTING remediation record."""
    reconciled_by: str = Field(default="system", min_length=1, description="Identity or operator performing reconciliation")
    ssm_command_id: Optional[str] = Field(default=None, description="Optional known SSM RunCommand ID if already observed")

    @field_validator("reconciled_by")
    @classmethod
    def sanitize_reconciler(cls, v: str) -> str:
        cleaned = (v or "system").strip()
        return cleaned or "system"


class ApprovalRecord(BaseModel):
    """Persistent approval and audit entity stored in DynamoDB."""
    approval_id: str = Field(..., description="Primary Key: UUID of the approval record")
    incident_id: str = Field(..., description="New Relic or correlated incident ID")
    event_id: str = Field(..., description="Unique idempotency event ID")
    service: str = Field(..., description="Target service name")
    target: str = Field(..., description="Target EC2 instance ID")
    recommended_action: str = Field(..., description="Allowlisted action")
    root_cause: str = Field(..., description="AI root cause diagnosis")
    confidence: float = Field(..., description="Confidence score")
    decision: str = Field(default="ALLOWLISTED_RECOMMENDATION", description="Phase 7 deterministic safety decision")
    approval_status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, description="Current approval state")
    created_at: str = Field(..., description="ISO 8601 UTC creation timestamp")
    expires_at: str = Field(..., description="ISO 8601 UTC expiration timestamp")
    ttl: int = Field(..., description="DynamoDB TTL epoch seconds")
    approved_by: Optional[str] = Field(default=None, description="Human approver")
    approved_at: Optional[str] = Field(default=None, description="ISO 8601 UTC approval timestamp")
    rejected_by: Optional[str] = Field(default=None, description="Human rejector")
    rejected_at: Optional[str] = Field(default=None, description="ISO 8601 UTC rejection timestamp")
    rejection_reason: Optional[str] = Field(default=None, description="Rejection reason")
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.NOT_EXECUTED, description="Execution status")
    execution_started_at: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp when execution was dispatched")
    execution_completed_at: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp when execution completed or verified")
    reconciled_at: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp of reconciliation if applicable")
    reconciled_by: Optional[str] = Field(default=None, description="Identity or operator who performed reconciliation")
    reconciliation_evidence: Optional[Dict[str, Any]] = Field(default=None, description="Evidence gathered during reconciliation")
    execution_result: Optional[Dict[str, Any]] = Field(default=None, description="Result payload from Phase 6 Lambda or SSM")
    ssm_command_id: Optional[str] = Field(default=None, description="SSM RunCommand CommandId if executed")
    error_message: Optional[str] = Field(default=None, description="Error details if execution or approval failed")
    evidence: List[str] = Field(default_factory=list, description="Diagnostic evidence points")
    reasoning_summary: Optional[str] = Field(default=None, description="Analytical reasoning summary")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata")

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        """Checks if current time has passed expires_at."""
        now = current_time or datetime.now(timezone.utc)
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return now >= exp
        except Exception:
            return False


class ApprovalResponse(BaseModel):
    """UI and API response model for remediation approvals."""
    approval_id: str
    incident_id: str
    event_id: str
    service: str
    target: str
    recommended_action: str
    root_cause: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float
    decision: str
    approval_status: ApprovalStatus
    created_at: str
    expires_at: str
    is_expired: bool
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    execution_status: ExecutionStatus
    execution_started_at: Optional[str] = None
    execution_completed_at: Optional[str] = None
    reconciled_at: Optional[str] = None
    reconciled_by: Optional[str] = None
    reconciliation_evidence: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    ssm_command_id: Optional[str] = None
    error_message: Optional[str] = None
    reasoning_summary: Optional[str] = None

    @classmethod
    def from_record(cls, record: ApprovalRecord) -> "ApprovalResponse":
        return cls(
            approval_id=record.approval_id,
            incident_id=record.incident_id,
            event_id=record.event_id,
            service=record.service,
            target=record.target,
            recommended_action=record.recommended_action,
            root_cause=record.root_cause,
            evidence=record.evidence,
            confidence=record.confidence,
            decision=record.decision,
            approval_status=record.approval_status,
            created_at=record.created_at,
            expires_at=record.expires_at,
            is_expired=record.is_expired(),
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            rejected_by=record.rejected_by,
            rejected_at=record.rejected_at,
            rejection_reason=record.rejection_reason,
            execution_status=record.execution_status,
            execution_started_at=record.execution_started_at,
            execution_completed_at=record.execution_completed_at,
            reconciled_at=record.reconciled_at,
            reconciled_by=record.reconciled_by,
            reconciliation_evidence=record.reconciliation_evidence,
            execution_result=record.execution_result,
            ssm_command_id=record.ssm_command_id,
            error_message=record.error_message,
            reasoning_summary=record.reasoning_summary,
        )

