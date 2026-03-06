"""
Redpanda event schemas.

Each model here maps 1:1 to a Redpanda topic. When a service publishes
or consumes from a topic, it serializes/deserializes using these models.
This guarantees type safety across service boundaries.

Topic mapping:
    crawl.requests       -> CrawlRequestEvent
    crawl.results        -> CrawlResultEvent
    extraction.requests  -> ExtractionRequestEvent
    extraction.results   -> ExtractionResultEvent

All topics are keyed by job_id, which ensures ordered processing per job
(all messages for one job land on the same partition).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from arachne_models.jobs import JobPriority


class CrawlRequestEvent(BaseModel):
    """Published to 'crawl.requests' when a new crawl task is dispatched.

    This is the lightweight event version (for the broker). The full
    CrawlRequest with headers/proxy config is passed via Temporal activities.
    """

    job_id: UUID
    url: HttpUrl
    attempt: int
    priority: JobPriority
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CrawlResultEvent(BaseModel):
    """Published to 'crawl.results' after a crawl attempt completes.

    Downstream consumers (extraction workers, status updaters) subscribe
    to this topic to react to completed crawls.
    """

    job_id: UUID
    url: HttpUrl
    success: bool
    status_code: int
    raw_html_ref: str | None = None  # MinIO object reference
    error: str | None = None
    elapsed_ms: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractionRequestEvent(BaseModel):
    """Published to 'extraction.requests' after successful crawl.

    Carries the MinIO reference to raw HTML, not the HTML itself
    (Claim-Check pattern). Extraction workers pull HTML from MinIO.
    """

    job_id: UUID
    raw_html_ref: str  # MinIO object reference
    extraction_schema: dict | None = None
    extraction_method: str = "css_xpath"  # "css_xpath" | "llm" | "auto_schema"
    model_preference: str | None = None  # LiteLLM model id override
    cost_mode: str | None = None  # "minimize" | "balanced" | "accuracy"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractionResultEvent(BaseModel):
    """Published to 'extraction.results' after extraction completes.

    Small results are inlined in extracted_data. Large results go to
    MinIO and only the result_ref is set (Claim-Check again).
    """

    job_id: UUID
    success: bool
    extracted_data: dict | None = None  # Inline for small results
    result_ref: str | None = None  # MinIO reference for large results
    error: str | None = None
    extraction_method: str = "css_xpath"  # "css_xpath" | "llm" | "vision" | "auto_schema"
    model_used: str | None = None  # LLM model used for extraction
    tokens_input: int | None = None  # Input token count
    tokens_output: int | None = None  # Output token count
    estimated_cost_usd: float | None = None  # Extraction cost
    confidence: float | None = None  # Extraction confidence
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
