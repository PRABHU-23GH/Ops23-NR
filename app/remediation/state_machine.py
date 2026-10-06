"""Strict state machine for Phase 8 remediation approvals.

Defines valid state transitions and guards against illegal transitions.
"""

from typing import Tuple
from app.remediation.models import ApprovalStatus


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal approval state transition is attempted."""
    pass


# Map of allowed source states to target states
ALLOWED_TRANSITIONS = {
    ApprovalStatus.PENDING: {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    },
    ApprovalStatus.APPROVED: {
        ApprovalStatus.APPROVED,  # Idempotent re-approval
        ApprovalStatus.EXECUTING,
        ApprovalStatus.EXPIRED,
    },
    ApprovalStatus.EXECUTING: {
        ApprovalStatus.EXECUTED,
        ApprovalStatus.EXECUTION_FAILED,
    },
    ApprovalStatus.EXECUTED: set(),  # Terminal state
    ApprovalStatus.REJECTED: set(),  # Terminal state
    ApprovalStatus.EXPIRED: set(),   # Terminal state
    ApprovalStatus.EXECUTION_FAILED: set(),  # Terminal state
}


def can_transition(current: ApprovalStatus, target: ApprovalStatus) -> bool:
    """Returns True if transition from current to target is permissible."""
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: ApprovalStatus, target: ApprovalStatus) -> Tuple[bool, str]:
    """Validates state transition and returns (is_valid, reason)."""
    if current == ApprovalStatus.APPROVED and target == ApprovalStatus.APPROVED:
        return True, "Idempotent re-approval"

    if current == ApprovalStatus.PENDING and target == ApprovalStatus.EXECUTED:
        return False, "Direct transition PENDING -> EXECUTED is strictly forbidden. Explicit human approval is required."

    if current == ApprovalStatus.PENDING and target == ApprovalStatus.EXECUTING:
        return False, "Direct transition PENDING -> EXECUTING is strictly forbidden. Remediation must be APPROVED first."

    if current == ApprovalStatus.EXECUTED and target == ApprovalStatus.APPROVED:
        return False, "Cannot approve an already executed remediation. Transition EXECUTED -> APPROVED is rejected."

    if current == ApprovalStatus.REJECTED:
        return False, f"Approval is already REJECTED. Cannot transition to {target}."

    if current == ApprovalStatus.EXPIRED:
        return False, f"Approval is EXPIRED. Cannot transition to {target}."

    if current == ApprovalStatus.EXECUTED:
        return False, f"Approval is already EXECUTED. Replay execution is forbidden."

    if current == ApprovalStatus.EXECUTION_FAILED:
        return False, f"Approval has failed execution. Cannot transition to {target}."

    if can_transition(current, target):
        return True, f"Valid transition {current} -> {target}"

    return False, f"Illegal state transition: {current} -> {target}"


def assert_transition_allowed(current: ApprovalStatus, target: ApprovalStatus) -> None:
    """Raises InvalidStateTransitionError if transition is invalid."""
    is_valid, reason = validate_transition(current, target)
    if not is_valid:
        raise InvalidStateTransitionError(reason)
