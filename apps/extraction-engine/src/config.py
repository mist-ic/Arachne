"""
Extraction engine configuration.

Manages all settings for the AI extraction service: model configuration,
cost limits, Ollama endpoint, LLM API keys, and CAPTCHA solver preferences.

Uses pydantic-settings for environment variable loading with the ARACHNE_ prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class ExtractionEngineSettings(BaseSettings):
    """Settings for the extraction engine service.

    All settings can be overridden via environment variables prefixed
    with ARACHNE_. E.g., ARACHNE_GEMINI_API_KEY, ARACHNE_OLLAMA_BASE_URL.
    """

    model_config = {"env_prefix": "ARACHNE_"}

    # --- Infrastructure ---
    temporal_address: str = Field(
        default="localhost:7233",
        description="Temporal server address",
    )
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://arachne:arachne@localhost:5432/arachne",
        description="PostgreSQL connection string",
    )
    minio_endpoint: str = Field(default="localhost:9000")
    minio_access_key: str = Field(default="arachne")
    minio_secret_key: str = Field(default="arachne123")
    redpanda_brokers: str = Field(default="localhost:9092")

    # --- Ollama (Local Models) ---
    ollama_base_url: str = Field(
        default="http://ollama:11434",
        description="Ollama API base URL for local model inference",
    )
    ollama_default_model: str = Field(
        default="qwen3:8b",
        description="Default Ollama model for extraction",
    )

    # --- LLM API Keys ---
    gemini_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (optional)",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        description="Anthropic API key (optional)",
    )

    # --- Extraction Routing ---
    default_model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="Default LiteLLM model for extraction",
    )
    cost_mode: str = Field(
        default="balanced",
        description="Routing cost mode: minimize | balanced | accuracy",
    )
    max_cost_per_page_usd: float = Field(
        default=0.10,
        description="Hard cost ceiling per page extraction (USD)",
    )
    max_latency_ms: int = Field(
        default=30_000,
        description="Maximum acceptable extraction latency (ms)",
    )

    # --- CAPTCHA Solving ---
    captcha_local_model: str = Field(
        default="qwen3-vl:32b",
        description="Ollama vision model for local CAPTCHA solving",
    )
    captcha_2captcha_key: str | None = Field(
        default=None,
        description="2Captcha API key for external CAPTCHA solving",
    )
    captcha_capsolver_key: str | None = Field(
        default=None,
        description="CapSolver API key for external CAPTCHA solving",
    )

    # --- Worker Configuration ---
    task_queue: str = Field(
        default="extract-ai",
        description="Temporal task queue name for this worker",
    )
    max_concurrent_activities: int = Field(
        default=5,
        description="Maximum concurrent extraction activities",
    )
    log_level: str = Field(default="INFO")

    def get_api_keys(self) -> dict[str, str]:
        """Get all configured API keys as a dictionary."""
        keys: dict[str, str] = {}
        if self.gemini_api_key:
            keys["GEMINI_API_KEY"] = self.gemini_api_key
        if self.openai_api_key:
            keys["OPENAI_API_KEY"] = self.openai_api_key
        if self.anthropic_api_key:
            keys["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        return keys
