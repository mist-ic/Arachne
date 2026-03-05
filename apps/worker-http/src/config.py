"""
Worker configuration via pydantic-settings.

All settings are loaded from environment variables (prefixed with ARACHNE_)
and can be overridden via a .env file. This is the standard pattern for
12-factor app configuration.

Note: Uses pydantic_settings.BaseSettings, NOT pydantic.BaseSettings.
      It was split into a separate package in Pydantic v2.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class WorkerConfig(BaseSettings):
    """Configuration for the HTTP crawler worker.

    All fields can be set via environment variables with ARACHNE_ prefix:
        ARACHNE_TEMPORAL_ADDRESS=temporal:7233
        ARACHNE_POSTGRES_DSN=postgresql+asyncpg://...
    """

    # Temporal
    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "scrape-http"
    temporal_namespace: str = "default"

    # Redpanda
    redpanda_brokers: str = "localhost:19092"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "arachne"
    minio_secret_key: str = "arachne123"

    # PostgreSQL
    postgres_dsn: str = "postgresql+asyncpg://arachne:arachne@localhost:5432/arachne"

    # Worker tuning
    max_concurrent_activities: int = 10
    http_timeout_seconds: int = 25

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "ARACHNE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
