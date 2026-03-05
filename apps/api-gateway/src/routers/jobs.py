"""
Jobs router — CRUD + workflow dispatch for scrape jobs.

Endpoints:
    POST   /api/v1/jobs           — Submit a new scrape job
    GET    /api/v1/jobs           — List all jobs (paginated)
    GET    /api/v1/jobs/{id}      — Get job details
    GET    /api/v1/jobs/{id}/attempts — Get crawl attempt history
    DELETE /api/v1/jobs/{id}      — Cancel a job

The POST endpoint is the most important: it creates a DB record,
starts a Temporal workflow, and returns immediately. The workflow
runs asynchronously — clients poll GET /jobs/{id} for status.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client as TemporalClient

from arachne_models.db.repositories import CrawlAttemptRepository, JobRepository
from arachne_models.jobs import JobCreate, JobPriority, JobStatus
from dependencies import get_db, get_temporal

router = APIRouter()


# ============================================================================
# Response schemas (what the API returns to clients)
# ============================================================================

class JobResponse(BaseModel):
    """Job details returned by the API."""

    id: uuid.UUID
    url: str
    status: str
    priority: str
    max_retries: int
    retry_count: int
    raw_html_ref: str | None = None
    result_ref: str | None = None
    error_message: str | None = None
    last_status_code: int | None = None
    extraction_schema: dict | None = None
    metadata: dict = {}
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    jobs: list[JobResponse]
    total: int
    limit: int
    offset: int


class JobCreateResponse(BaseModel):
    """Response after creating a job (includes workflow_id)."""

    id: uuid.UUID
    url: str
    status: str
    workflow_id: str
    message: str


class CrawlAttemptResponse(BaseModel):
    """Details of a single crawl attempt."""

    id: uuid.UUID
    attempt_number: int
    url: str
    status_code: int | None = None
    elapsed_ms: int | None = None
    proxy_used: str | None = None
    error: str | None = None
    raw_html_ref: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ============================================================================
# Endpoints
# ============================================================================

@router.post("", response_model=JobCreateResponse, status_code=201)
async def create_job(
    job_in: JobCreate,
    db: AsyncSession = Depends(get_db),
    temporal: TemporalClient = Depends(get_temporal),
):
    """Submit a new scrape job.

    Creates a job record in PostgreSQL, then starts a Temporal workflow
    to execute the scrape pipeline. Returns immediately — the workflow
    runs asynchronously.

    The workflow_id can be used to track the workflow in the Temporal UI
    at http://localhost:8088.

    Example request:
    ```json
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
    ```
    """
    # 1. Create job in PostgreSQL
    repo = JobRepository(db)
    job = await repo.create(job_in)
    await db.commit()

    # 2. Start Temporal workflow
    workflow_id = f"scrape-{job.id}"

    await temporal.start_workflow(
        "ScrapeWorkflow",
        {
            "job_id": str(job.id),
            "url": str(job_in.url),
            "max_retries": job_in.max_retries,
            "headers": None,
            "extraction_schema": job_in.extraction_schema,
        },
        id=workflow_id,
        task_queue="scrape-http",
    )

    # 3. Update status to queued
    await repo.update_status(job.id, JobStatus.QUEUED)
    await db.commit()

    return JobCreateResponse(
        id=job.id,
        url=str(job_in.url),
        status="queued",
        workflow_id=workflow_id,
        message="Job submitted. Track status at GET /api/v1/jobs/{id}",
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all jobs with optional status filter and pagination."""
    repo = JobRepository(db)

    if status:
        jobs = await repo.list_by_status(status, limit=limit, offset=offset)
        total = await repo.count(status=status)
    else:
        jobs = await repo.list_all(limit=limit, offset=offset)
        total = await repo.count()

    return JobListResponse(
        jobs=[_to_response(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed status of a specific job."""
    repo = JobRepository(db)
    job = await repo.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return _to_response(job)


@router.get("/{job_id}/attempts", response_model=list[CrawlAttemptResponse])
async def get_job_attempts(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all crawl attempts for a job (audit trail).

    Shows every HTTP request made, including failed attempts with
    status codes, timing, proxy used, and error messages. Essential
    for debugging anti-bot escalation in Phase 2.
    """
    # Verify job exists
    job_repo = JobRepository(db)
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    attempt_repo = CrawlAttemptRepository(db)
    attempts = await attempt_repo.get_by_job(job_id)
    return attempts


@router.delete("/{job_id}", status_code=204)
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or running job.

    Sets job status to 'cancelled'. Does not terminate an in-progress
    Temporal workflow (that requires Temporal API cancellation, added
    in a future step).
    """
    repo = JobRepository(db)
    job = await repo.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is already in terminal state: {job.status}",
        )

    await repo.update_status(job_id, JobStatus.CANCELLED)
    await db.commit()


# ============================================================================
# Helpers
# ============================================================================

def _to_response(job) -> JobResponse:
    """Convert a JobRow ORM object to a JobResponse Pydantic model."""
    return JobResponse(
        id=job.id,
        url=job.url,
        status=job.status,
        priority=job.priority,
        max_retries=job.max_retries,
        retry_count=job.retry_count,
        raw_html_ref=job.raw_html_ref,
        result_ref=job.result_ref,
        error_message=job.error_message,
        last_status_code=job.last_status_code,
        extraction_schema=job.extraction_schema,
        metadata=job.metadata_ if hasattr(job, 'metadata_') else {},
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )
