"""Health check endpoint for Ops23-NR.

This endpoint is intentionally lightweight so it can be queried rapidly
by automated recovery scripts, AWS Systems Manager, AWS Lambda,
and New Relic synthetics without imposing resource overhead.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Health response payload schema."""

    status: str = Field(default="healthy", description="Current health status of the service")
    service: str = Field(description="Service identifier")
    version: str = Field(description="Semantic version of the application")
    environment: str = Field(description="Operational environment")
    timestamp: str = Field(description="ISO-8601 UTC timestamp of the health check")


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Health Check",
    description="Returns service availability, version, and environment. Used for health verification in self-healing loops.",
)
async def get_health() -> HealthResponse:
    """Return lightweight health check status."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
