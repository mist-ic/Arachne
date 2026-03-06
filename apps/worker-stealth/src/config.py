"""
Stealth worker configuration via pydantic-settings.

Extends the base worker config pattern with browser-specific settings
(backend selection, headless mode, proxy configuration).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class StealthWorkerConfig(BaseSettings):
    """Configuration for the stealth browser worker.

    All fields can be set via environment variables with ARACHNE_ prefix:
        ARACHNE_TEMPORAL_ADDRESS=temporal:7233
        ARACHNE_BROWSER_BACKEND=camoufox
    """

    # Temporal
    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "scrape-stealth"
    temporal_namespace: str = "default"

    # Redpanda
    redpanda_brokers: str = "localhost:19092"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "arachne"
    minio_secret_key: str = "arachne123"

    # PostgreSQL
    postgres_dsn: str = "postgresql+asyncpg://arachne:arachne@localhost:5432/arachne"

    # Browser settings
    browser_backend: str = "camoufox"  # "camoufox" or "pydoll"
    browser_headless: bool = True
    browser_timeout: int = 30
    auto_solve_cloudflare: bool = True

    # Worker tuning
    max_concurrent_activities: int = 3  # Lower than HTTP worker — browsers are heavy
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "ARACHNE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
