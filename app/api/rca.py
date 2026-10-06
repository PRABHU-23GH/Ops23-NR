"""FastAPI Router for Amazon Bedrock Root Cause Analysis (RCA).

Phase 7: Controlled API Endpoint for Diagnostic Evidence Analysis.
"""

from fastapi import APIRouter, Depends, status
from app.config import Settings, get_settings
from app.rca.models import RCARequest, RCAResponse
from app.rca.service import RCAService

router = APIRouter(prefix="/api/v1/rca", tags=["Root Cause Analysis"])


def get_rca_service(settings: Settings = Depends(get_settings)) -> RCAService:
    """Dependency injection provider for RCAService."""
    return RCAService(settings=settings)


@router.post(
    "/analyze",
    response_model=RCAResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Incident Root Cause",
    description=(
        "Submits diagnostic telemetry evidence to Amazon Bedrock for structured Root Cause Analysis (RCA). "
        "Enforces deterministic safety boundary validation. Phase 7 is analysis-only."
    ),
)
async def analyze_incident(
    request: RCARequest,
    rca_service: RCAService = Depends(get_rca_service),
) -> RCAResponse:
    """Analyze incident evidence and return structured RCA response with safety validation."""
    return rca_service.analyze_incident(request)
