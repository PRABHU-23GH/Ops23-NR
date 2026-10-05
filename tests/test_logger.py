"""Unit tests for structured JSON logging and sensitive data protection."""

import io
import json
import logging
from app.logger import StructuredJsonFormatter, sanitize_value


def test_structured_json_formatter_fields():
    """Verify that all required log fields are present in the serialized JSON output."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test_file.py",
        lineno=10,
        msg="Test message content",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345"
    record.endpoint = "/test/endpoint"
    record.http_method = "GET"
    record.http_path = "/test/endpoint"
    record.http_status_code = 200
    record.duration = 0.0125

    formatted = formatter.format(record)
    log_dict = json.loads(formatted)

    required_fields = [
        "timestamp",
        "level",
        "service",
        "logger",
        "message",
        "request_id",
        "trace_id",
        "span_id",
        "endpoint",
        "http_method",
        "http_path",
        "http_status_code",
        "duration",
        "environment",
    ]

    for field in required_fields:
        assert field in log_dict, f"Missing required log field: {field}"

    assert log_dict["level"] == "INFO"
    assert log_dict["service"] == "Ops23-NR"
    assert log_dict["request_id"] == "req-12345"
    assert log_dict["endpoint"] == "/test/endpoint"
    assert log_dict["http_status_code"] == 200
    assert log_dict["duration"] == 0.0125


def test_sensitive_data_redaction():
    """Verify that credentials, tokens, and secrets are redacted."""
    sensitive_keys = [
        ("password", "supersecret123"),
        ("authorization", "Bearer my-token-abc"),
        ("api_key", "nr-ingest-key-xyz"),
        ("client_secret", "secret-key-456"),
        ("token", "session-token-789"),
    ]

    for key, value in sensitive_keys:
        redacted = sanitize_value(key, value)
        assert redacted == "[REDACTED]", f"Key {key} was not redacted!"

    # Safe keys should remain untouched
    assert sanitize_value("user_id", "usr-101") == "usr-101"
    assert sanitize_value("status", "active") == "active"
