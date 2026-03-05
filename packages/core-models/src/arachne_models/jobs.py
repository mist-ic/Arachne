"""
Job lifecycle models.

These models define the complete lifecycle of a scrape job:
- JobCreate: What the user submits via the API
- Job: Full record as stored in PostgreSQL
- JobStatus/JobPriority: Enum constraints

A Job moves through: pending -> queued -> running -> completed/failed/cancelled
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(StrEnum):
    """State machine for job lifecycle.

    Transitions:
        pending -> queued (workflow started in Temporal)
        queued -> running (worker picks up the job)
        running -> completed (extraction successful)
        running -> failed (max retries exhausted)
        pending/queued/running -> cancelled (user cancellation)
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(StrEnum):
    """Job priority levels. Higher priority jobs are processed first.

    CRITICAL jobs bypass normal queue ordering (used for internal retries
    after anti-bot escalation in Phase 2).
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class JobCreate(BaseModel):
    """What the user submits via POST /api/v1/jobs.

    Only `url` is required. Everything else has sensible defaults.

    Example:
        {
            "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
            "priority": "normal",
            "max_retries": 3,
            "extraction_schema": {
                "fields": {
                    "title": {"selector": "h1", "type": "text"},
                    "price": {"selector": ".price_color", "type": "text"}
                }
            }
        }
    """

    url: HttpUrl
    priority: JobPriority = JobPriority.NORMAL
    max_retries: int = Field(default=3, ge=0, le=10)
    callback_url: HttpUrl | None = None
    extraction_schema: dict | None = None
    metadata: dict = Field(default_factory=dict)


class Job(BaseModel):
    """Full job record as stored in PostgreSQL.

    Created from a JobCreate submission, enriched with system fields
    (id, timestamps, status tracking, result references).

    The result_ref and raw_html_ref fields follow the Claim-Check pattern:
    they store MinIO object references (e.g. "minio://arachne-raw-html/raw/...")
    instead of inline data, keeping the database lean.
    """

    id: UUID = Field(default_factory=uuid4)
    url: HttpUrl
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    max_retries: int = 3
    retry_count: int = 0

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    # Error tracking
    error_message: str | None = None

    # Claim-Check references (MinIO object IDs, not inline data)
    result_ref: str | None = None
    raw_html_ref: str | None = None

    # User-provided or auto-discovered extraction schema
    extraction_schema: dict | None = None

    # Arbitrary user metadata (tags, source identifiers, etc.)
    metadata: dict = Field(default_factory=dict)
