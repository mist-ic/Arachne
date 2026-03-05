"""
API Gateway configuration via pydantic-settings.

12-factor config loaded from environment variables with ARACHNE_ prefix.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class APIConfig(BaseSettings):
    """Configuration for the FastAPI API Gateway."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Temporal
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "scrape-http"

    # PostgreSQL
    postgres_dsn: str = "postgresql+asyncpg://arachne:arachne@localhost:5432/arachne"

    # Redpanda
    redpanda_brokers: str = "localhost:19092"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "arachne"
    minio_secret_key: str = "arachne123"

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "ARACHNE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
