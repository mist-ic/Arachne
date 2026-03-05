"""
Temporal activities — individual units of work in the scrape pipeline.

Each activity is a single, focused, independently retryable function.
Temporal calls these from within the ScrapeWorkflow. If an activity
fails, Temporal retries it (or not) based on the retry policy.

Activities in this file:
    fetch_url           — HTTP GET a URL, return HTML + metadata
    store_raw_html      — Upload HTML to MinIO, return reference
    publish_crawl_result — Publish event to Redpanda crawl.results topic
    update_job_status   — Update job record in PostgreSQL
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

import httpx
from temporalio import activity

from errors import (
    FetchError,
    HTTP401Error,
    HTTP403Error,
    HTTP404Error,
    HTTP407Error,
    HTTP429Error,
    HTTP503Error,
    NetworkError,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Data classes for activity inputs/outputs (must be serializable)
# ============================================================================

# Basic User-Agent rotation — not stealth, just variety.
# Phase 2 replaces this with browser-fingerprint-matched UA strings.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


@dataclass
class FetchResult:
    """Output of the fetch_url activity."""
    html: str
    status_code: int
    headers: dict[str, str]
    elapsed_ms: int


@dataclass
class StoreResult:
    """Output of the store_raw_html activity."""
    raw_html_ref: str
    size_bytes: int


# ============================================================================
# Activities
# ============================================================================

@activity.defn
async def fetch_url(url: str, headers: dict[str, str] | None = None) -> FetchResult:
    """Fetch a URL using httpx. Phase 1 — no TLS spoofing.

    In Phase 2, this switches to curl_cffi for browser-identical TLS/JA4
    fingerprints. The activity interface stays the same — only the
    HTTP client implementation changes.

    Error routing:
        403 → HTTP403Error (retryable — Phase 2 escalates to browser)
        429 → HTTP429Error (retryable with backoff)
        503 → HTTP503Error (retryable — transient server issue)
        404 → HTTP404Error (non-retryable — dead resource)
        401 → HTTP401Error (non-retryable — needs auth)

    Args:
        url: Target URL to fetch.
        headers: Optional request headers. User-Agent auto-rotated if not set.

    Returns:
        FetchResult with HTML, status code, response headers, and timing.
    """
    request_headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if headers:
        request_headers.update(headers)

    activity.logger.info(f"Fetching {url}")
    start = perf_counter()

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(25.0, connect=10.0),
        ) as client:
            response = await client.get(url, headers=request_headers)
    except httpx.ConnectError as e:
        raise NetworkError(f"Connection failed: {url}", url=url) from e
    except httpx.TimeoutException as e:
        raise NetworkError(f"Timeout: {url}", url=url) from e
    except httpx.HTTPError as e:
        raise NetworkError(f"HTTP error: {url} — {e}", url=url) from e

    elapsed_ms = int((perf_counter() - start) * 1000)

    # Route errors to typed exceptions for Temporal retry policy
    match response.status_code:
        case 403:
            raise HTTP403Error(f"Blocked by anti-bot: {url}", status_code=403, url=url)
        case 429:
            raise HTTP429Error(f"Rate limited: {url}", status_code=429, url=url)
        case 503:
            raise HTTP503Error(f"Server overloaded: {url}", status_code=503, url=url)
        case 404:
            raise HTTP404Error(f"Not found: {url}", status_code=404, url=url)
        case 401:
            raise HTTP401Error(f"Auth required: {url}", status_code=401, url=url)
        case 407:
            raise HTTP407Error(f"Proxy auth required: {url}", status_code=407, url=url)

    # Raise for any other 4xx/5xx not explicitly handled
    response.raise_for_status()

    activity.logger.info(f"Fetched {url} — {response.status_code} in {elapsed_ms}ms ({len(response.text)} chars)")

    return FetchResult(
        html=response.text,
        status_code=response.status_code,
        headers=dict(response.headers),
        elapsed_ms=elapsed_ms,
    )


@activity.defn
async def store_raw_html(job_id: str, html: str) -> StoreResult:
    """Store raw HTML in MinIO using the Claim-Check pattern.

    The HTML content goes to MinIO. Only the reference string
    (e.g. "minio://arachne-raw-html/raw/{job_id}/{ts}.html") is returned
    and passed through the rest of the pipeline.

    Args:
        job_id: UUID string of the job.
        html: Raw HTML content to store.

    Returns:
        StoreResult with MinIO reference and size in bytes.
    """
    from arachne_storage import ArachneStorage

    storage = ArachneStorage()
    ref = storage.store_raw_html(job_id, html)
    size = len(html.encode("utf-8"))

    activity.logger.info(f"Stored raw HTML for job {job_id} — {size} bytes → {ref}")

    return StoreResult(raw_html_ref=ref, size_bytes=size)


@activity.defn
async def publish_crawl_result(
    job_id: str,
    url: str,
    success: bool,
    status_code: int,
    raw_html_ref: str | None,
    elapsed_ms: int,
    error: str | None = None,
) -> None:
    """Publish a crawl result event to the Redpanda crawl.results topic.

    Downstream consumers (extraction workers, status updaters, dashboard)
    subscribe to this topic to react to completed crawls.

    Args:
        job_id: UUID string of the job.
        url: URL that was crawled.
        success: Whether the crawl succeeded.
        status_code: HTTP status code received.
        raw_html_ref: MinIO reference (None if crawl failed).
        elapsed_ms: Time taken in milliseconds.
        error: Error message if crawl failed.
    """
    from arachne_messaging import ArachneProducer
    from arachne_models.events import CrawlResultEvent

    event = CrawlResultEvent(
        job_id=job_id,
        url=url,
        success=success,
        status_code=status_code,
        raw_html_ref=raw_html_ref,
        elapsed_ms=elapsed_ms,
        error=error,
    )

    producer = ArachneProducer()
    producer.publish("crawl.results", key=job_id, event=event)
    producer.close()

    activity.logger.info(f"Published crawl result for job {job_id} — success={success}")


@activity.defn
async def update_job_status(
    job_id: str,
    status: str,
    error_message: str | None = None,
    raw_html_ref: str | None = None,
    result_ref: str | None = None,
) -> None:
    """Update job status in PostgreSQL.

    Uses the repository pattern from packages/core-models. Creates a
    short-lived async session for each status update.

    This activity is called at multiple points in the workflow:
    - queued → running (when worker picks up the job)
    - running → completed (after successful extraction)
    - running → failed (after max retries exhausted)

    Args:
        job_id: UUID string of the job.
        status: New status value.
        error_message: Error details (for failed status).
        raw_html_ref: MinIO reference to raw HTML (for completed).
        result_ref: MinIO reference to extracted data (for completed).
    """
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from arachne_models.db.repositories import JobRepository
    from config import WorkerConfig

    config = WorkerConfig()
    engine = create_async_engine(config.postgres_dsn)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        repo = JobRepository(session)
        await repo.update_status(
            uuid.UUID(job_id),
            status,
            error_message=error_message,
            raw_html_ref=raw_html_ref,
            result_ref=result_ref,
        )
        await session.commit()

    await engine.dispose()

    activity.logger.info(
        f"Job {job_id} status → {status}"
        + (f" (error: {error_message})" if error_message else "")
    )


@activity.defn
async def record_crawl_attempt(
    job_id: str,
    attempt_number: int,
    url: str,
    status_code: int | None = None,
    elapsed_ms: int | None = None,
    proxy_used: str | None = None,
    error: str | None = None,
    raw_html_ref: str | None = None,
    response_headers: dict | None = None,
) -> None:
    """Record a crawl attempt in the crawl_attempts table.

    Every HTTP request gets logged — successes and failures alike.
    This creates the audit trail visible at GET /api/v1/jobs/{id}/attempts.

    Args:
        job_id: UUID string of the job.
        attempt_number: Which attempt this is (1-based).
        url: URL that was fetched.
        status_code: HTTP status code (None if network error).
        elapsed_ms: Request duration.
        proxy_used: Proxy address if one was used.
        error: Error message if the attempt failed.
        raw_html_ref: MinIO reference if HTML was stored.
        response_headers: Response headers dict.
    """
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from arachne_models.db.repositories import CrawlAttemptRepository
    from config import WorkerConfig

    config = WorkerConfig()
    engine = create_async_engine(config.postgres_dsn)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        repo = CrawlAttemptRepository(session)
        await repo.create(
            job_id=uuid.UUID(job_id),
            attempt_number=attempt_number,
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            proxy_used=proxy_used,
            error=error,
            raw_html_ref=raw_html_ref,
            response_headers=response_headers,
        )
        await session.commit()

    await engine.dispose()

    activity.logger.info(
        f"Recorded crawl attempt #{attempt_number} for job {job_id} — "
        + (f"status={status_code}" if status_code else f"error={error}")
    )

