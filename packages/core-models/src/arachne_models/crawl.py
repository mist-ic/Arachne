"""
Crawl request and result models.

These models describe what flows between the API gateway, Temporal workflows,
and crawler workers:
- CrawlRequest: Task sent to a crawler worker (via Temporal activity)
- CrawlResult: What the crawler returns after fetching a page

The raw HTML itself is NOT in these models. It goes to MinIO (Claim-Check
pattern), and only the reference string (raw_html_ref) travels through
the system. This keeps messages small and the broker happy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class CrawlRequest(BaseModel):
    """Task dispatched to a crawler worker.

    In Phase 1 this is passed directly as a Temporal activity argument.
    In Phase 2, the Evasion Router may modify headers and proxy_config
    before dispatching to the appropriate worker tier.
    """

    job_id: UUID
    url: HttpUrl
    attempt: int = 1
    headers: dict[str, str] = Field(default_factory=dict)
    proxy_config: dict | None = None


class CrawlResult(BaseModel):
    """Result returned by a crawler worker after fetching a URL.

    Key design: raw HTML is NOT inline. The worker stores it in MinIO
    and only passes the reference here. This is the Claim-Check pattern
    from enterprise integration patterns.

    Why:
    - Raw HTML can be 500KB-5MB per page
    - Redpanda messages should stay under 1MB
    - MinIO gives us versioning, lifecycle policies, and S3 API for free
    """

    job_id: UUID
    url: HttpUrl
    status_code: int
    raw_html_ref: str  # e.g. "minio://arachne-raw-html/raw/{job_id}/{ts}.html"
    response_headers: dict[str, str] = Field(default_factory=dict)
    elapsed_ms: int
    proxy_used: str | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
