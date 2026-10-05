"""Pytest fixtures and configuration for Ops23-NR test suite.

Ensures the testing environment flag is active and process termination is disabled.
Also initializes in-memory OpenTelemetry span capture for safe local test verification.
"""

import os
from typing import Generator
import pytest
from fastapi.testclient import TestClient

# Enforce safe environment variables for testing
os.environ["TESTING"] = "true"
os.environ["ALLOW_PROCESS_TERMINATION"] = "false"
os.environ["ENVIRONMENT"] = "testing"
os.environ["OTEL_ENABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "in_memory"

from app.config import get_settings
from app.tracing import reset_in_memory_spans, setup_in_memory_tracing
from app.main import app


@pytest.fixture(autouse=True)
def enforce_test_settings():
    """Verify settings before each test to guarantee safety and clean spans."""
    settings = get_settings()
    settings.TESTING = True
    settings.ALLOW_PROCESS_TERMINATION = False
    settings.OTEL_ENABLED = True
    settings.OTEL_TRACES_EXPORTER = "in_memory"
    setup_in_memory_tracing(settings)
    reset_in_memory_spans()
    yield
    reset_in_memory_spans()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient fixture with app lifecycle handling."""
    with TestClient(app) as test_client:
        yield test_client
