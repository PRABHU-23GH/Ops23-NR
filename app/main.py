"""Main FastAPI application entrypoint for Ops23-NR.

Configures application lifecycle, structured JSON logging middleware,
OpenTelemetry distributed tracing, global exception handlers, and API route registrations.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import time
import uuid
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.approvals import router as approvals_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.rca import router as rca_router
from app.api.simulate import SimulatedApplicationError, router as simulate_router
from app.api.users import router as users_router
from app.config import get_settings
from app.logger import (
    duration_ctx,
    endpoint_ctx,
    http_method_ctx,
    http_path_ctx,
    http_status_code_ctx,
    logger,
    request_id_ctx,
    setup_logging,
)
from app.tracing import (
    init_tracing,
    instrument_fastapi,
    shutdown_tracing,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for startup and shutdown hooks."""
    settings = get_settings()
    setup_logging()
    init_tracing(settings)

    logger.info(
        f"{settings.SERVICE_NAME} starting up in {settings.ENVIRONMENT} mode (v{settings.VERSION}).",
        extra={
            "extra_fields": {
                "event": "application_startup",
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
                "host": settings.HOST,
                "port": settings.PORT,
                "otel_enabled": settings.OTEL_ENABLED,
                "otel_service_name": settings.OTEL_SERVICE_NAME,
            }
        },
    )
    yield
    logger.info(
        f"{settings.SERVICE_NAME} shutting down.",
        extra={"extra_fields": {"event": "application_shutdown"}},
    )
    shutdown_tracing()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    application = FastAPI(
        title="Ops23-NR — Intelligent Cloud Observability & Self-Healing Platform",
        description=(
            "Production-grade FastAPI foundation designed for full-stack observability with New Relic, "
            "OpenTelemetry distributed tracing, automated recovery with AWS Systems Manager & Lambda, and AI RCA."
        ),
        version=settings.VERSION,
        lifespan=lifespan,
    )

    # -------------------------------------------------------------------------
    # Structured Request / Response Middleware
    # -------------------------------------------------------------------------
    @application.middleware("http")
    async def structured_logging_middleware(request: Request, call_next) -> Response:
        """Capture timing, extract or generate request_id, and emit structured JSON logs."""
        # Correlate or generate request ID
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        path = request.url.path
        method = request.method

        # Bind context variables for structured logger
        req_id_token = request_id_ctx.set(req_id)
        method_token = http_method_ctx.set(method)
        path_token = http_path_ctx.set(path)
        endpoint_token = endpoint_ctx.set(path)

        start_time = time.perf_counter()
        status_code = 500

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = req_id
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration = round(time.perf_counter() - start_time, 6)
            duration_ctx.set(duration)
            http_status_code_ctx.set(status_code)

            log_msg = f"HTTP {method} {path} returned status {status_code} in {duration:.4f}s"
            log_extras = {
                "request_id": req_id,
                "endpoint": path,
                "http_method": method,
                "http_path": path,
                "http_status_code": status_code,
                "duration": duration,
            }

            if status_code >= 500:
                logger.error(log_msg, extra=log_extras)
            elif status_code >= 400:
                logger.warning(log_msg, extra=log_extras)
            else:
                logger.info(log_msg, extra=log_extras)

            # Reset context variables
            request_id_ctx.reset(req_id_token)
            http_method_ctx.reset(method_token)
            http_path_ctx.reset(path_token)
            endpoint_ctx.reset(endpoint_token)

    # -------------------------------------------------------------------------
    # OpenTelemetry Instrumentation
    # -------------------------------------------------------------------------
    instrument_fastapi(application)

    # -------------------------------------------------------------------------
    # Exception Handlers
    # -------------------------------------------------------------------------
    @application.exception_handler(SimulatedApplicationError)
    async def simulated_error_handler(
        request: Request, exc: SimulatedApplicationError
    ) -> JSONResponse:
        """Handle controlled failure simulations and emit structured ERROR logs."""
        req_id = request_id_ctx.get()
        now = datetime.now(timezone.utc).isoformat()

        logger.error(
            f"Simulated controlled exception occurred: {exc.message}",
            exc_info=True,
            extra={
                "extra_fields": {
                    "event": "simulated_application_error",
                    "error_code": exc.error_code,
                    "error_message": exc.message,
                    "request_id": req_id,
                    "endpoint": request.url.path,
                }
            },
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "SimulatedApplicationError",
                "error_code": exc.error_code,
                "message": exc.message,
                "request_id": req_id,
                "timestamp": now,
            },
            headers={"x-request-id": req_id},
        )

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all unhandled exception handler with structured ERROR logging."""
        req_id = request_id_ctx.get()
        now = datetime.now(timezone.utc).isoformat()

        logger.error(
            f"Unhandled exception during request processing: {str(exc)}",
            exc_info=True,
            extra={
                "extra_fields": {
                    "event": "unhandled_server_exception",
                    "exception_type": type(exc).__name__,
                    "request_id": req_id,
                    "endpoint": request.url.path,
                }
            },
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred. Correlate with request_id in logs.",
                "request_id": req_id,
                "timestamp": now,
            },
            headers={"x-request-id": req_id},
        )

    # -------------------------------------------------------------------------
    # Root Route
    # -------------------------------------------------------------------------
    @application.get(
        "/",
        status_code=status.HTTP_200_OK,
        summary="Service Information",
        description="Returns basic metadata and status of the Ops23-NR platform.",
    )
    async def root_index() -> dict[str, str]:
        """Root endpoint returning service identity."""
        return {
            "service": settings.SERVICE_NAME,
            "title": "Ops23-NR — Intelligent Cloud Observability & Self-Healing Platform",
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "status": "running",
            "docs_url": "/docs",
        }

    # -------------------------------------------------------------------------
    # Route Registration
    # -------------------------------------------------------------------------
    application.include_router(health_router)
    application.include_router(users_router)
    application.include_router(orders_router)
    application.include_router(simulate_router)
    application.include_router(rca_router)
    application.include_router(approvals_router)

    return application



# Default application instance for ASGI servers (uvicorn app.main:app)
app = create_app()
