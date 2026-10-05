# Ops23-NR Observability & Distributed Tracing Guide

**Phase 2: OpenTelemetry Distributed Tracing**

---

## 1. Overview: OpenTelemetry in Ops23-NR

In Phase 2, Ops23-NR introduces vendor-neutral distributed tracing using the [OpenTelemetry Python SDK](https://opentelemetry.io/). 

The goal of this phase is to establish standard telemetry contracts, automatically capture HTTP server spans for every incoming request, extract span attributes, and correlate distributed traces (`trace_id` and `span_id`) directly into structured JSON logs.

```
Incoming HTTP Request (e.g. GET /health)
         │
         ▼
[ OpenTelemetry FastAPI Instrumentor ]
         │  • Creates Root SERVER Span
         │  • Injects trace_id & span_id into active context
         │  • Records http.method, http.status_code, http.route, http.url
         │
         ▼
[ Structured Logging Middleware & Handlers ]
         │  • Queries trace context (get_trace_correlation)
         │  • Formats: trace_id (32-hex) + span_id (16-hex)
         │  • Emits structured JSON with request_id + trace_id + span_id
         │
         ▼
[ OpenTelemetry TracerProvider & Exporters ]
         │  • Development / Testing: InMemorySpanExporter or ConsoleSpanExporter
         │  • Production / Staging: OTLPSpanExporter (HTTP/gRPC)
         ▼
[ Downstream Telemetry Backend (New Relic in Phase 3 - NOT IMPLEMENTED) ]
```

---

## 2. Configuration & Supported Environment Variables

OpenTelemetry tracing is configured dynamically through standard environment variables or a local `.env` file via [app/config.py](file:///d:/Ops23-NR/app/config.py):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `OTEL_ENABLED` | boolean | `true` | Master toggle to enable or disable OpenTelemetry tracing. |
| `OTEL_SERVICE_NAME` | string | `Ops23-NR` | Logical service identifier set on the OpenTelemetry Resource (`service.name`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | string | `""` (empty) | Target OTLP collector or New Relic OTLP ingest endpoint (e.g. `https://otlp.nr-data.net:4318/v1/traces`). |
| `OTEL_EXPORTER_OTLP_HEADERS` | string | `""` (empty) | Comma-separated key=value pairs for OTLP authentication headers (e.g. `api-key=YOUR_NR_LICENSE_KEY`). |
| `OTEL_TRACES_EXPORTER` | string | `otlp` | Exporter type. Supported values: `otlp`, `in_memory`, `console`, `none`. |
| `OTEL_TRACES_SAMPLER` | string | `parentbased_traceidratio` | Sampling strategy: `parentbased_traceidratio`, `always_on`, `always_off`, `traceidratio`. |
| `OTEL_TRACES_SAMPLER_ARG` | float | `1.0` | Sampling ratio between `0.0` and `1.0` (1.0 = 100% trace sampling). |

> **Security Guard:** Never commit real API keys or tokens to Git or `.env` files. In local development and automated tests, `OTEL_EXPORTER_OTLP_ENDPOINT` remains empty or points to `in_memory`.

---

## 3. How Tracing is Enabled or Disabled

### Disabling Tracing Completely
Set `OTEL_ENABLED=false` in the environment or `.env`:

```bash
OTEL_ENABLED=false
```

When disabled:
- [init_tracing()](file:///d:/Ops23-NR/app/tracing.py) skips `TracerProvider` creation and returns `None`.
- `FastAPIInstrumentor` is not attached to the FastAPI application.
- The application starts up normally without any tracing overhead.
- Structured logs output `"-"` for `trace_id` and `span_id`.

### Enabling Tracing Locally with In-Memory / Console Export
To inspect spans locally without any external network services:

```bash
OTEL_ENABLED=true
OTEL_TRACES_EXPORTER=in_memory
```
Or for human-readable terminal output:
```bash
OTEL_ENABLED=true
OTEL_TRACES_EXPORTER=console
```

---

## 4. Log and Trace Correlation

Ops23-NR correlates structured logs with active distributed traces without replacing the standard Python logging system.

Inside [app/logger.py](file:///d:/Ops23-NR/app/logger.py), the `StructuredJsonFormatter` extracts the active OpenTelemetry span context using `get_trace_correlation()` from [app/tracing.py](file:///d:/Ops23-NR/app/tracing.py).

### Example Correlated Structured Log
```json
{
  "timestamp": "2026-10-05T07:56:22.093708+00:00",
  "level": "INFO",
  "service": "Ops23-NR",
  "logger": "ops23.app",
  "message": "HTTP GET /health returned status 200 in 0.0014s",
  "request_id": "6ca11c1f-3bbf-4293-9ccd-6878ed93d3f4",
  "trace_id": "e1493a8b5d62d11d9d21634f6aa6a2be",
  "span_id": "b3045d50faeff954",
  "endpoint": "/health",
  "http_method": "GET",
  "http_path": "/health",
  "http_status_code": 200,
  "duration": 0.001401,
  "environment": "development"
}
```

This format allows log ingestion engines (like New Relic or CloudWatch) to jump seamlessly between logs, APM transactions, and distributed waterfall traces using `trace_id`.

---

## 5. Local Testing & Verification Procedure

### Automated Testing via Pytest
The test suite utilizes the `InMemorySpanExporter` fixture to verify span creation without external dependencies:

```bash
pytest -q
```

All 16 tests pass, validating:
- In-memory span generation on `/health`
- Service resource attributes (`service.name`, `service.version`, `deployment.environment`)
- HTTP attributes (`http.method`, `http.status_code`)
- Tracing disabled mode (`OTEL_ENABLED=false`)
- Configuration and header parsing
- Trace and log ID correlation
- Error status recording on `/api/simulate/error`

### Manual Local Verification
1. Start the application:
   ```bash
   uvicorn app.main:app --port 8003 --reload
   ```
2. In another terminal, query endpoints:
   ```bash
   curl http://127.0.0.1:8003/health
   curl http://127.0.0.1:8003/api/users
   curl -X POST http://127.0.0.1:8003/api/simulate/error
   ```
3. Observe the stdout console logs: each log line includes `trace_id` and `span_id` correlated with the request.

---

## 6. Planned Future Integration: New Relic (Phase 3 - NOT IMPLEMENTED)

> **IMPORTANT:** New Relic integration is intentionally **NOT IMPLEMENTED** in Phase 2.

In Phase 3, traces generated by OpenTelemetry in Ops23-NR will be exported to New Relic via OTLP/HTTP:
- **Endpoint**: `https://otlp.nr-data.net:4318/v1/traces` (US) or `https://otlp.eu01.nr-data.net:4318/v1/traces` (EU)
- **Headers**: `api-key=YOUR_NEW_RELIC_LICENSE_KEY`
- **Tracing Exporter**: `OTEL_TRACES_EXPORTER=otlp`

Because Ops23-NR adheres to open standards, exporting to New Relic will only require setting these environment variables without rewriting any application code.
