"""Configuration management for Ops23-NR using Pydantic Settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Application Configuration
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = "Ops23-NR"
    APP_NAME: str = "Ops23-NR-API"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    VERSION: str = "0.1.0"

    # Observability & Logging Configuration
    LOG_LEVEL: str = "INFO"

    # OpenTelemetry Tracing Configuration
    OTEL_ENABLED: bool = True
    OTEL_SERVICE_NAME: str = "Ops23-NR"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_TRACES_EXPORTER: str = "otlp"
    OTEL_TRACES_SAMPLER: str = "parentbased_traceidratio"
    OTEL_TRACES_SAMPLER_ARG: float = 1.0

    # Safety Controls
    ALLOW_PROCESS_TERMINATION: bool = False
    TESTING: bool = False


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
