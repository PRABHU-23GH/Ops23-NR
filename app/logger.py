"""Structured JSON logging module for Ops23-NR.

Emits machine-readable JSON logs correlated with request IDs and
OpenTelemetry trace/span IDs for APM, distributed tracing, and New Relic log aggregation.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from app.config import get_settings

# Context variables to bind request metadata across async call boundaries
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
endpoint_ctx: ContextVar[str] = ContextVar("endpoint", default="-")
http_method_ctx: ContextVar[str] = ContextVar("http_method", default="-")
http_path_ctx: ContextVar[str] = ContextVar("http_path", default="-")
http_status_code_ctx: ContextVar[int | None] = ContextVar("http_status_code", default=None)
duration_ctx: ContextVar[float | None] = ContextVar("duration", default=None)

# Keys that must NEVER appear in logs
SENSITIVE_KEYS = {
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
}


def sanitize_value(key: str, value: Any) -> Any:
    """Mask sensitive key-value pairs."""
    if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(key, item) for item in value]
    return value


class StructuredJsonFormatter(logging.Formatter):
    """Custom logging formatter that produces clean, structured JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        settings = get_settings()

        # Extract OpenTelemetry trace and span context if available
        trace_id = getattr(record, "trace_id", None)
        span_id = getattr(record, "span_id", None)

        if not trace_id or not span_id:
            try:
                from app.tracing import get_trace_correlation
                t_id, s_id = get_trace_correlation()
                trace_id = trace_id or t_id
                span_id = span_id or s_id
            except Exception:
                trace_id = trace_id or "-"
                span_id = span_id or "-"

        # Build base structured log payload
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.SERVICE_NAME,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_ctx.get()),
            "trace_id": trace_id,
            "span_id": span_id,
            "endpoint": getattr(record, "endpoint", endpoint_ctx.get()),
            "http_method": getattr(record, "http_method", http_method_ctx.get()),
            "http_path": getattr(record, "http_path", http_path_ctx.get()),
            "http_status_code": getattr(record, "http_status_code", http_status_code_ctx.get()),
            "duration": getattr(record, "duration", duration_ctx.get()),
            "environment": settings.ENVIRONMENT,
        }

        # Include exception information if available
        if record.exc_info:
            log_payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": self.formatException(record.exc_info),
            }

        # Include any custom extra fields passed to logger
        custom_extras = getattr(record, "extra_fields", None)
        if custom_extras and isinstance(custom_extras, dict):
            for k, v in custom_extras.items():
                if k not in log_payload:
                    log_payload[k] = sanitize_value(k, v)

        return json.dumps(log_payload, default=str)


def setup_logging(log_level: str | None = None) -> logging.Logger:
    """Configure structured JSON logging for the application."""
    settings = get_settings()
    level = log_level or settings.LOG_LEVEL

    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to prevent duplicate or unstructured lines
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # Stream structured JSON to stdout for container / systemd journal collection
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(StructuredJsonFormatter())
    stream_handler.setLevel(numeric_level)
    root_logger.addHandler(stream_handler)

    # Adjust third-party library loggers
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False

    app_logger = logging.getLogger("ops23.app")
    app_logger.setLevel(numeric_level)
    return app_logger


# Global application logger
logger = logging.getLogger("ops23.app")
