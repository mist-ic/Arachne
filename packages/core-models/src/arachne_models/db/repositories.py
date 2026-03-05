"""
Repository pattern for database access.

Clean abstraction over SQLAlchemy queries. Each repository provides
typed CRUD operations for one aggregate root. Services call repositories
instead of writing raw SQL or SQLAlchemy queries.

This pattern:
- Centralizes all database logic in one place
- Makes unit testing easy (mock the repository, not the DB)
- Keeps service code clean and focused on business logic
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from arachne_models.db.models import CrawlAttemptRow, EntityRow, JobRow
from arachne_models.jobs import JobCreate, JobStatus


class JobRepository:
    """CRUD operations for the jobs table.

    Usage:
        repo = JobRepository(session)
        job = await repo.create(JobCreate(url="https://..."))
        job = await repo.get(job_id)
        await repo.update_status(job_id, JobStatus.COMPLETED)
        jobs = await repo.list_by_status(JobStatus.PENDING, limit=10)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, job_in: JobCreate) -> JobRow:
        """Create a new job from API input."""
        job = JobRow(
            url=str(job_in.url),
            priority=job_in.priority.value,
            max_retries=job_in.max_retries,
            extraction_schema=job_in.extraction_schema,
            metadata_=job_in.metadata,
        )
        self.session.add(job)
        await self.session.flush()  # Get the generated ID
        return job

    async def get(self, job_id: uuid.UUID) -> JobRow | None:
        """Get a job by ID. Returns None if not found."""
        return await self.session.get(JobRow, job_id)

    async def update_status(
        self,
        job_id: uuid.UUID,
        status: JobStatus | str,
        *,
        error_message: str | None = None,
        raw_html_ref: str | None = None,
        result_ref: str | None = None,
        last_status_code: int | None = None,
    ) -> None:
        """Update job status and optional fields.

        Automatically sets completed_at when status is 'completed' or 'failed',
        and increments retry_count on retry-related updates.
        """
        values: dict = {
            "status": status if isinstance(status, str) else status.value,
            "updated_at": datetime.now(timezone.utc),
        }

        if error_message is not None:
            values["error_message"] = error_message
        if raw_html_ref is not None:
            values["raw_html_ref"] = raw_html_ref
        if result_ref is not None:
            values["result_ref"] = result_ref
        if last_status_code is not None:
            values["last_status_code"] = last_status_code

        # Auto-set completed_at for terminal states
        status_str = values["status"]
        if status_str in ("completed", "failed", "cancelled"):
            values["completed_at"] = datetime.now(timezone.utc)

        stmt = update(JobRow).where(JobRow.id == job_id).values(**values)
        await self.session.execute(stmt)

    async def increment_retry(self, job_id: uuid.UUID) -> None:
        """Increment the retry counter for a job."""
        stmt = (
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(
                retry_count=JobRow.retry_count + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    async def list_by_status(
        self,
        status: JobStatus | str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRow]:
        """List jobs filtered by status, ordered by creation time."""
        status_val = status if isinstance(status, str) else status.value
        stmt = (
            select(JobRow)
            .where(JobRow.status == status_val)
            .order_by(JobRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[JobRow]:
        """List all jobs, ordered by creation time."""
        stmt = (
            select(JobRow)
            .order_by(JobRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, status: JobStatus | str | None = None) -> int:
        """Count jobs, optionally filtered by status."""
        stmt = select(func.count(JobRow.id))
        if status is not None:
            status_val = status if isinstance(status, str) else status.value
            stmt = stmt.where(JobRow.status == status_val)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def delete(self, job_id: uuid.UUID) -> bool:
        """Delete a job. Returns True if deleted, False if not found."""
        job = await self.get(job_id)
        if job is None:
            return False
        await self.session.delete(job)
        return True


class EntityRepository:
    """CRUD operations for the entities table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        job_id: uuid.UUID,
        entity_type: str,
        data: dict,
        source_url: str,
        raw_html_ref: str | None = None,
        schema_hash: str | None = None,
    ) -> EntityRow:
        """Create a new extracted entity."""
        # Determine version (auto-increment per job+type)
        stmt = (
            select(func.coalesce(func.max(EntityRow.version), 0))
            .where(EntityRow.job_id == job_id, EntityRow.entity_type == entity_type)
        )
        result = await self.session.execute(stmt)
        max_version = result.scalar_one()

        entity = EntityRow(
            job_id=job_id,
            entity_type=entity_type,
            data=data,
            source_url=source_url,
            raw_html_ref=raw_html_ref,
            schema_hash=schema_hash,
            version=max_version + 1,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_by_job(self, job_id: uuid.UUID) -> list[EntityRow]:
        """Get all entities for a job."""
        stmt = select(EntityRow).where(EntityRow.job_id == job_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CrawlAttemptRepository:
    """CRUD operations for the crawl_attempts table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        job_id: uuid.UUID,
        attempt_number: int,
        url: str,
        status_code: int | None = None,
        elapsed_ms: int | None = None,
        proxy_used: str | None = None,
        error: str | None = None,
        raw_html_ref: str | None = None,
        response_headers: dict | None = None,
    ) -> CrawlAttemptRow:
        """Record a crawl attempt."""
        attempt = CrawlAttemptRow(
            job_id=job_id,
            attempt_number=attempt_number,
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            proxy_used=proxy_used,
            error=error,
            raw_html_ref=raw_html_ref,
            response_headers=response_headers,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def get_by_job(self, job_id: uuid.UUID) -> list[CrawlAttemptRow]:
        """Get all crawl attempts for a job, ordered by attempt number."""
        stmt = (
            select(CrawlAttemptRow)
            .where(CrawlAttemptRow.job_id == job_id)
            .order_by(CrawlAttemptRow.attempt_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
