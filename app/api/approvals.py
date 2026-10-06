"""FastAPI router for Phase 8 Human-in-the-Loop Remediation Approvals.

Endpoints:
- POST /api/v1/remediation/approvals
- GET  /api/v1/remediation/approvals/{approval_id}
- POST /api/v1/remediation/approvals/{approval_id}/approve
- POST /api/v1/remediation/approvals/{approval_id}/reject
- POST /api/v1/remediation/approvals/{approval_id}/execute
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.remediation.models import (
    ApprovalResponse,
    ApproveRequest,
    CreateApprovalRequest,
    ExecuteRemediationRequest,
    ReconcileRequest,
    RejectRequest,
    validate_human_identity,
)
from app.remediation.service import RemediationApprovalService

logger = logging.getLogger("ops23.api.approvals")

router = APIRouter(
    prefix="/api/v1/remediation/approvals",
    tags=["Human-in-the-Loop Remediation Approvals"],
)


def get_approval_service() -> RemediationApprovalService:
    """Dependency provider for RemediationApprovalService."""
    return RemediationApprovalService()


def verify_approval_auth(
    x_approval_token: Annotated[Optional[str], Header()] = None,
    x_approver_id: Annotated[Optional[str], Header()] = None,
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """Validates POC authentication and caller human identity headers."""
    if settings.APPROVAL_AUTH_ENABLED:
        # If token authentication is enabled, verify token matches configured secret
        expected = settings.APPROVAL_DEV_TOKEN
        if expected and x_approval_token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Missing or invalid X-Approval-Token.",
            )

    if x_approver_id:
        try:
            validate_human_identity(x_approver_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            )

    return x_approver_id


@router.post(
    "",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Pending Remediation Approval",
    description="Submits a validated RCA recommendation to create an auditable, pending approval.",
)
async def create_approval(
    request: CreateApprovalRequest,
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    try:
        record = service.create_approval(request)
        return ApprovalResponse.from_record(record)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating approval: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create approval: {str(e)}",
        )


@router.get(
    "/{approval_id}",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Approval Details and Audit History",
    description="Retrieves status, evidence, confidence, and audit history for a specific approval ID.",
)
async def get_approval(
    approval_id: str,
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    record = service.get_approval(approval_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval record '{approval_id}' not found.",
        )
    return ApprovalResponse.from_record(record)


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve Remediation Recommendation",
    description="Authorizes execution of an allowlisted recommendation by capturing human identity.",
)
async def approve_remediation(
    approval_id: str,
    body: ApproveRequest,
    auth_identity: Optional[str] = Depends(verify_approval_auth),
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    # Use body identity or fallback to header identity
    approver = body.approved_by or auth_identity
    if not approver:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required human approver identity.",
        )

    try:
        validate_human_identity(approver)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    body.approved_by = approver

    try:
        record = service.approve_remediation(approval_id, body)
        return ApprovalResponse.from_record(record)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error approving remediation {approval_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve remediation: {str(e)}",
        )


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject Remediation Recommendation",
    description="Rejects a pending recommendation and permanently closes the approval cycle.",
)
async def reject_remediation(
    approval_id: str,
    body: RejectRequest,
    auth_identity: Optional[str] = Depends(verify_approval_auth),
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    rejector = body.rejected_by or auth_identity
    if not rejector:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required human rejector identity.",
        )

    try:
        validate_human_identity(rejector)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    body.rejected_by = rejector

    try:
        record = service.reject_remediation(approval_id, body)
        return ApprovalResponse.from_record(record)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error rejecting remediation {approval_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject remediation: {str(e)}",
        )


@router.post(
    "/{approval_id}/execute",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute Approved Remediation",
    description=(
        "Dispatches execution of a validated and approved remediation to Phase 6 Lambda. "
        "Strictly loads parameters from storage; caller cannot supply arbitrary commands or instances."
    ),
)
async def execute_remediation(
    approval_id: str,
    body: ExecuteRemediationRequest,
    auth_identity: Optional[str] = Depends(verify_approval_auth),
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    executor = body.executed_by or auth_identity
    if not executor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required human operator identity.",
        )

    try:
        validate_human_identity(executor)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    body.executed_by = executor

    try:
        record = service.execute_remediation(approval_id, body)
        return ApprovalResponse.from_record(record)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error executing remediation {approval_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Remediation execution dispatch failed: {str(e)}",
        )


@router.post(
    "/{approval_id}/reconcile",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Safely Reconcile Remediation State",
    description=(
        "Safely reconciles an existing EXECUTING approval record against verified SSM execution "
        "and application health evidence without dispatching any new remediation."
    ),
)
async def reconcile_remediation(
    approval_id: str,
    body: Optional[ReconcileRequest] = None,
    auth_identity: Optional[str] = Depends(verify_approval_auth),
    service: RemediationApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    req = body or ReconcileRequest(reconciled_by=auth_identity or "system")
    if auth_identity and (not req.reconciled_by or req.reconciled_by == "system"):
        req.reconciled_by = auth_identity

    try:
        record = service.reconcile_execution(approval_id, req)
        return ApprovalResponse.from_record(record)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error reconciling remediation {approval_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Remediation reconciliation failed: {str(e)}",
        )

