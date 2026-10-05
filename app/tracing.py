"""OpenTelemetry Distributed Tracing configuration and instrumentation for Ops23-NR.

Phase 2: Local distributed tracing with OpenTelemetry SDK, FastAPI instrumentation,
service resources, configurable OTLP / in-memory exporters, and log correlation.
"""

from typing import Any, Dict, List, Optional, Tuple
import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.semconv.resource import ResourceAttributes

from app.config import Settings, get_settings

logger = logging.getLogger("ops23.app")

# Global singleton references for tracing lifecycle
_tracer_provider: Optional[TracerProvider] = None
_in_memory_exporter: Optional[InMemorySpanExporter] = None
_exporter_attached: bool = False


def parse_otlp_headers(headers_str: str) -> Dict[str, str]:
    """Parse comma-separated key=value string into a headers dictionary."""
    headers: Dict[str, str] = {}
    if not headers_str or not headers_str.strip():
        return headers
    for item in headers_str.split(","):
        if "=" in item:
            key, val = item.split("=", 1)
            headers[key.strip()] = val.strip()
    return headers


def get_sampler(sampler_name: str, sampler_arg: float) -> Any:
    """Resolve OpenTelemetry Sampler instance based on configuration name and argument."""
    name = (sampler_name or "").strip().lower()
    if name in ("always_on", "alwayson", "true"):
        return ALWAYS_ON
    elif name in ("always_off", "alwaysoff", "false"):
        return ALWAYS_OFF
    elif name in ("traceidratio", "trace_id_ratio"):
        return TraceIdRatioBased(sampler_arg)
    elif name in ("parentbased_traceidratio", "parentbased_trace_id_ratio", "parent_based"):
        return ParentBased(TraceIdRatioBased(sampler_arg))
    return ParentBased(TraceIdRatioBased(sampler_arg))


def create_span_exporter(settings: Settings) -> Optional[SpanExporter]:
    """Create span exporter based on OTEL_TRACES_EXPORTER and endpoint configuration."""
    global _in_memory_exporter
    exporter_type = (settings.OTEL_TRACES_EXPORTER or "otlp").strip().lower()

    if exporter_type in ("none", "false", "disabled"):
        return None

    if exporter_type == "in_memory":
        if _in_memory_exporter is None:
            _in_memory_exporter = InMemorySpanExporter()
        return _in_memory_exporter

    if exporter_type == "console":
        return ConsoleSpanExporter()

    if exporter_type in ("otlp", "otlp_http", "otlp_grpc"):
        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.strip()
        headers = parse_otlp_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)

        if not endpoint:
            # Safe local fallback: no remote endpoint configured, avoid crashing or network errors
            return None

        # Normalize endpoint: ensure standard /v1/traces signal path for OTLP HTTP
        target_endpoint = endpoint if endpoint.endswith("/v1/traces") else f"{endpoint.rstrip('/')}/v1/traces"

        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as OTLPHttpSpanExporter,
            )

            return OTLPHttpSpanExporter(
                endpoint=target_endpoint,
                headers=headers if headers else None,
            )
        except Exception as exc:
            logger.warning(
                f"Failed to initialize OTLP exporter for endpoint '{target_endpoint}': {exc}. Tracing will operate locally without remote export."
            )
            return None

    logger.warning(f"Unrecognized OTEL_TRACES_EXPORTER: '{exporter_type}'. No exporter attached.")
    return None


def init_tracing(settings: Optional[Settings] = None) -> Optional[TracerProvider]:
    """Initialize OpenTelemetry TracerProvider with resource attributes and span processors."""
    global _tracer_provider, _in_memory_exporter, _exporter_attached
    app_settings = settings or get_settings()

    if not app_settings.OTEL_ENABLED:
        logger.info("OpenTelemetry tracing is disabled (OTEL_ENABLED=false).")
        return None

    # Check if a TracerProvider is already established globally
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        _tracer_provider = current
    elif _tracer_provider is not None:
        pass
    else:
        try:
            # Build service resource descriptor
            resource = Resource.create(
                {
                    ResourceAttributes.SERVICE_NAME: app_settings.OTEL_SERVICE_NAME or app_settings.SERVICE_NAME,
                    ResourceAttributes.SERVICE_VERSION: app_settings.VERSION,
                    ResourceAttributes.DEPLOYMENT_ENVIRONMENT: app_settings.ENVIRONMENT,
                }
            )

            sampler = get_sampler(
                app_settings.OTEL_TRACES_SAMPLER,
                app_settings.OTEL_TRACES_SAMPLER_ARG,
            )

            provider = TracerProvider(
                resource=resource,
                sampler=sampler,
            )
            trace.set_tracer_provider(provider)
            _tracer_provider = provider

            logger.info(
                f"OpenTelemetry tracing initialized for service '{app_settings.OTEL_SERVICE_NAME}' "
                f"(exporter: {app_settings.OTEL_TRACES_EXPORTER}, sampler: {app_settings.OTEL_TRACES_SAMPLER})."
            )
        except Exception as exc:
            logger.error(
                f"Graceful fallback: OpenTelemetry tracing initialization failed: {exc}",
                exc_info=True,
            )
            return None

    # Attach exporter to the active provider once
    if not _exporter_attached and _tracer_provider is not None:
        exporter = create_span_exporter(app_settings)
        if exporter is not None:
            if isinstance(exporter, InMemorySpanExporter):
                _tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
            else:
                _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            _exporter_attached = True

    return _tracer_provider


def setup_in_memory_tracing(settings: Optional[Settings] = None) -> InMemorySpanExporter:
    """Convenience helper for testing to ensure in-memory span collection is active."""
    global _in_memory_exporter, _tracer_provider
    app_settings = settings or get_settings()
    init_tracing(app_settings)

    if _in_memory_exporter is None:
        _in_memory_exporter = InMemorySpanExporter()
        if _tracer_provider is not None:
            _tracer_provider.add_span_processor(SimpleSpanProcessor(_in_memory_exporter))

    return _in_memory_exporter


def instrument_fastapi(app: FastAPI, tracer_provider: Optional[TracerProvider] = None) -> None:
    """Instrument the FastAPI application with OpenTelemetry server spans."""
    settings = get_settings()

    if not settings.OTEL_ENABLED:
        return

    try:
        provider = tracer_provider or _tracer_provider or trace.get_tracer_provider()
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="docs,openapi.json,redoc",
        )
        logger.info("FastAPI application instrumented with OpenTelemetry.")
    except Exception as exc:
        logger.error(f"Failed to instrument FastAPI application: {exc}", exc_info=True)


def shutdown_tracing() -> None:
    """Flush pending spans during application shutdown."""
    global _tracer_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.force_flush()
        except Exception as exc:
            logger.warning(f"Error flushing TracerProvider: {exc}")


def get_in_memory_spans() -> List[ReadableSpan]:
    """Retrieve finished spans from the InMemorySpanExporter if active (useful for testing)."""
    if _in_memory_exporter is not None:
        return _in_memory_exporter.get_finished_spans()
    return []


def reset_in_memory_spans() -> None:
    """Clear collected spans from InMemorySpanExporter."""
    if _in_memory_exporter is not None:
        _in_memory_exporter.clear()


def get_trace_correlation() -> Tuple[str, str]:
    """Extract the current active trace_id and span_id formatted as 32-hex and 16-hex strings.

    Returns:
        tuple[str, str]: (trace_id, span_id) or ("-", "-") if no active span context exists.
    """
    try:
        span = trace.get_current_span()
        span_ctx = span.get_span_context()
        if span_ctx.is_valid:
            trace_id = format(span_ctx.trace_id, "032x")
            span_id = format(span_ctx.span_id, "016x")
            return trace_id, span_id
    except Exception:
        pass
    return "-", "-"
