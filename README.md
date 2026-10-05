# Ops23-NR — Intelligent Cloud Observability & Self-Healing Platform

> Production-style FastAPI foundation for autonomous cloud observability, OpenTelemetry distributed tracing, incident detection, automated self-healing, and AI-powered root cause analysis.

---

## 1. Project Purpose

**Ops23-NR** is an intelligent observability and automated remediation platform designed to demonstrate modern Site Reliability Engineering (SRE) and AIOps practices.

The system monitors a cloud-hosted application, collects distributed traces and logs via OpenTelemetry, will forward telemetry to New Relic in subsequent phases, triggers automated remediation using AWS Lambda and AWS Systems Manager (SSM) without human intervention, verifies post-recovery application health, and leverages Amazon Bedrock to deliver automated Root Cause Analysis (RCA).

---

## 2. Technology Stack

### Current Implementation (Phase 1, Phase 2, & Phase 3A Complete)
- **Language**: Python 3.12+
- **API Framework**: FastAPI
- **ASGI Server**: Uvicorn
- **Distributed Tracing**: OpenTelemetry Python SDK & API (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp`)
- **Data Validation & Settings**: Pydantic v2 & Pydantic Settings
- **Structured Logging**: Standard Python `logging` with custom `JSONFormatter` correlating `request_id`, `trace_id`, and `span_id`
- **Cloud Infrastructure (IaC)**: HashiCorp Terraform (`aws_instance`, `aws_iam_role` for SSM, `aws_security_group`, `gp3` encrypted EBS)
- **Testing & Verification**: Pytest (16 tests passing), HTTPX, InMemorySpanExporter, Terraform validate & plan

### Architecture Progression
```
FastAPI (REST API)
   ↓
OpenTelemetry (Tracing & Telemetry Context)
   ↓
AWS EC2 (Amazon Linux 2023, SSM Managed - Terraform Defined)
   ↓
Future New Relic Integration (Phase 4 - NOT IMPLEMENTED)
```

---

## 3. Current Implementation Status

| Stage | Scope | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Application Foundation & Safe Testing | **COMPLETE** | FastAPI app, structured JSON logs, health probe, simulated datasets, guarded failure endpoints, full test suite. |
| **Phase 2** | OpenTelemetry Distributed Tracing | **COMPLETE** | OpenTelemetry SDK, FastAPI server spans, in-memory & OTLP export config, trace-to-log correlation (`trace_id`, `span_id`). |
| **Phase 3A**| AWS Infrastructure Preparation (Terraform) | **COMPLETE** | Terraform manifests for EC2 (t3.micro, AL2023), SSM IAM role, port 8000 security group, gp3 EBS. Validated via `terraform plan`. **Zero AWS deployments executed.** |
| **Phase 3B**| EC2 Deployment & Systemd Supervisor | **PLANNED** | Application deployment under Linux `systemd`. |
| **Phase 4** | New Relic Observability & Alerts | **PLANNED** | Not implemented yet. Zero New Relic packages or API keys required. |
| **Phase 5** | AWS Lambda & SSM Remediation | **PLANNED** | Not implemented yet. Zero Lambda or SSM scripts. |
| **Phase 6** | Amazon Bedrock AI RCA | **PLANNED** | Not implemented yet. |

---

## 4. Local Setup & Installation

### Prerequisites
- Python 3.12 or higher
- Git

### 1. Clone & Navigate to Repository
```bash
git clone <repository-url>
cd Ops23-NR
```

### 2. Create and Activate Virtual Environment
On Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 5. Running the Application Locally

Start the development server with Uvicorn (e.g. on port 8003):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8003 --reload
```

Or using the Python module:
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8003 --reload
```

Once running:
- **Interactive OpenAPI Documentation**: [http://127.0.0.1:8003/docs](http://127.0.0.1:8003/docs)
- **Alternative ReDoc Documentation**: [http://127.0.0.1:8003/redoc](http://127.0.0.1:8003/redoc)
- **Root Service Info**: [http://127.0.0.1:8003/](http://127.0.0.1:8003/)
- **Lightweight Health Check**: [http://127.0.0.1:8003/health](http://127.0.0.1:8003/health)
- **Users Dataset**: [http://127.0.0.1:8003/api/users](http://127.0.0.1:8003/api/users)
- **Orders Dataset**: [http://127.0.0.1:8003/api/orders](http://127.0.0.1:8003/api/orders)

---

## 6. Endpoints & API Reference

### Health & Information
- `GET /` — Returns service metadata, name, version, and environment.
- `GET /health` — Lightweight health check probe returning HTTP 200 and ISO timestamp. Used for recovery verification.

### Business Domain Simulation
- `GET /api/users` — Returns simulated users list for APM trace and traffic generation.
- `GET /api/orders` — Returns simulated customer orders list.

### Controlled Failure Simulation
- `POST /api/simulate/error` — Triggers a controlled `SimulatedApplicationError`, returning HTTP 500 and generating an `ERROR` structured log with traceback and correlated `trace_id`.
- `POST /api/simulate/crash` — Simulates a process crash.
  - **Safe Mode (Default & Automated Tests)**: When `ALLOW_PROCESS_TERMINATION=False` or `TESTING=True`, process exit is intercepted and suppressed. Returns HTTP 200 with safety status.
  - **Execution Mode (EC2 / Systemd Tests)**: When `ALLOW_PROCESS_TERMINATION=True` and `TESTING=False`, terminates process with exit code 1 to test supervisor self-healing.

---

## 7. OpenTelemetry Distributed Tracing & Logging

Every HTTP request produces a server span with standard HTTP and service attributes. In addition, the active OpenTelemetry `trace_id` and `span_id` are automatically captured and injected into every structured JSON log line.

See [docs/observability.md](file:///d:/Ops23-NR/docs/observability.md) for full details.

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
  "duration": 0.0014,
  "environment": "development"
}
```

> **Security Note:** Sensitive fields (such as `password`, `authorization`, `api_key`, `token`, and `secret`) are automatically masked with `[REDACTED]`.

---

## 8. Configuration

Configuration is managed via environment variables (or an optional `.env` file) with safe local defaults:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | string | `development` | Operational environment (e.g. `development`, `staging`, `production`) |
| `SERVICE_NAME` | string | `Ops23-NR` | Service identifier tag in logs and telemetry |
| `APP_NAME` | string | `Ops23-NR-API` | Application display name |
| `HOST` | string | `0.0.0.0` | Bind host address |
| `PORT` | integer | `8000` | Bind port number |
| `VERSION` | string | `0.1.0` | Semantic version |
| `LOG_LEVEL` | string | `INFO` | Minimum log severity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `OTEL_ENABLED` | boolean | `true` | Enable or disable OpenTelemetry distributed tracing |
| `OTEL_SERVICE_NAME` | string | `Ops23-NR` | Service name attribute in OpenTelemetry resource (`service.name`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT`| string | `""` | Target OTLP collector or New Relic endpoint (safe local fallback when empty) |
| `OTEL_EXPORTER_OTLP_HEADERS` | string | `""` | Comma-separated authentication headers for OTLP exporter |
| `OTEL_TRACES_EXPORTER` | string | `otlp` | Exporter type (`otlp`, `in_memory`, `console`, `none`) |
| `OTEL_TRACES_SAMPLER` | string | `parentbased_traceidratio`| Sampler strategy (`parentbased_traceidratio`, `always_on`, `always_off`, `traceidratio`) |
| `OTEL_TRACES_SAMPLER_ARG` | float | `1.0` | Sampling ratio (1.0 = 100% trace sampling) |
| `ALLOW_PROCESS_TERMINATION` | boolean | `false` | Safety toggle for crash simulation. Must be explicitly set to `true` to terminate process. |
| `TESTING` | boolean | `false` | Flag indicating automated test environment. Always disables process termination. |

---

## 9. Running Tests

Run the complete Pytest suite (16 tests passing):

```bash
pytest -q
```

With verbose output and log capturing:
```bash
pytest -v -s
```

All tests execute safely using an in-memory span exporter without requiring network calls or a New Relic account.
