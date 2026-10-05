"""Failure simulation endpoints for Ops23-NR.

Enables controlled generation of HTTP 500 exceptions (to validate New Relic
alert policies and error rate detection) and process crashes (to validate
systemd automatic restarts and AWS Lambda/SSM self-healing workflows).
"""

import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.logger import logger

router = APIRouter(prefix="/api/simulate", tags=["Failure Simulation"])


class SimulatedApplicationError(Exception):
    """Controlled application exception used for observability testing."""

    def __init__(self, message: str = "Simulated application failure for observability testing", error_code: str = "SIM_ERR_500"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class ErrorSimulationRequest(BaseModel):
    """Payload schema for triggering controlled error."""

    error_code: str = Field(
        default="SIM_ERR_500",
        description="Application error code to identify the failure type",
    )
    detail: str = Field(
        default="Simulated internal server exception for observability testing",
        description="Descriptive message describing the simulated error condition",
    )


class CrashSimulationRequest(BaseModel):
    """Payload schema for triggering process crash simulation."""

    reason: str = Field(
        default="Testing systemd auto-restart and self-healing",
        description="Reason for invoking simulated crash",
    )
    exit_code: int = Field(
        default=1,
        description="Exit status code for process termination",
    )


class CrashSimulationResponse(BaseModel):
    """Response schema for crash simulation."""

    status: str = Field(description="Crash simulation execution status")
    terminated: bool = Field(description="Whether the process will actually terminate")
    safety_guard: str = Field(description="State of the safety guard (active or disabled)")
    reason: str = Field(description="Trigger reason")
    message: str = Field(description="Details on execution or safe interception")
    exit_code: int = Field(description="Target exit code")
    timestamp: str = Field(description="ISO-8601 UTC timestamp")


# Configurable crash executor callback, defaults to os._exit.
# Can be mocked in tests to verify termination execution without killing pytest.
_crash_executor: Callable[[int], None] = os._exit


def set_crash_executor(executor: Callable[[int], None]) -> None:
    """Override crash executor (primarily for unit testing)."""
    global _crash_executor
    _crash_executor = executor


def reset_crash_executor() -> None:
    """Reset crash executor to default os._exit."""
    global _crash_executor
    _crash_executor = os._exit


@router.post(
    "/error",
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    summary="Simulate Application Exception",
    description="Raises a controlled SimulatedApplicationError resulting in an HTTP 500 response and structured ERROR log.",
)
async def simulate_error(request: Optional[ErrorSimulationRequest] = None) -> None:
    """Trigger a controlled application exception to test error tracking."""
    error_code = request.error_code if request else "SIM_ERR_500"
    detail = request.detail if request else "Simulated internal server exception for observability testing"
    raise SimulatedApplicationError(message=detail, error_code=error_code)


@router.post(
    "/crash",
    response_model=CrashSimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="Simulate Process Crash",
    description="Simulates an application crash for testing systemd process supervisors. Protected by safety guards.",
)
async def simulate_crash(request: Optional[CrashSimulationRequest] = None) -> CrashSimulationResponse:
    """Simulate application crash with safe interception for automated tests."""
    settings = get_settings()
    reason = request.reason if request else "Testing systemd auto-restart and self-healing"
    exit_code = request.exit_code if request else 1

    # Safe test mechanism: Process will NOT terminate if ALLOW_PROCESS_TERMINATION is False
    # or if running within a test suite (TESTING=True).
    if not settings.ALLOW_PROCESS_TERMINATION or settings.TESTING:
        logger.warning(
            "Simulated crash intercepted in SAFE mode. Actual process termination suppressed by safety guard.",
            extra={
                "extra_fields": {
                    "event": "simulated_crash_intercepted",
                    "safety_guard": "active",
                    "allow_process_termination": settings.ALLOW_PROCESS_TERMINATION,
                    "testing": settings.TESTING,
                    "target_exit_code": exit_code,
                    "reason": reason,
                }
            },
        )
        return CrashSimulationResponse(
            status="simulated_crash_intercepted",
            terminated=False,
            safety_guard="active",
            reason=reason,
            message=(
                "Process crash safely simulated. Actual termination suppressed by safety guard "
                "(ALLOW_PROCESS_TERMINATION=False or TESTING=True). Set ALLOW_PROCESS_TERMINATION=true "
                "in production/EC2 environment to enable actual process exit for systemd self-healing tests."
            ),
            exit_code=exit_code,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # When explicitly allowed (e.g. in EC2 systemd verification tests), execute termination
    logger.critical(
        f"Simulated crash initiated: Process will terminate with exit code {exit_code} for self-healing verification.",
        extra={
            "extra_fields": {
                "event": "simulated_crash_executing",
                "safety_guard": "disabled",
                "exit_code": exit_code,
                "reason": reason,
            }
        },
    )

    def _delayed_termination() -> None:
        # Give the server 50ms to finish transmitting the HTTP 200 response to client
        time.sleep(0.05)
        _crash_executor(exit_code)

    threading.Thread(target=_delayed_termination, daemon=True).start()

    return CrashSimulationResponse(
        status="simulated_crash_initiated",
        terminated=True,
        safety_guard="disabled",
        reason=reason,
        message=f"Process termination initiated with exit code {exit_code}. Systemd supervisor will trigger restart.",
        exit_code=exit_code,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
