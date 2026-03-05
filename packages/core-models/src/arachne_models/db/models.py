"""
SQLAlchemy ORM models mapped to PostgreSQL tables.

Uses SQLAlchemy 2.0+ Mapped[] annotations with mapped_column() instead
of the legacy Column() syntax. This gives full type checker support
(mypy/pyright know the types of every column).

Tables:
    jobs            — Tracks every scrape request through its lifecycle
    entities        — Extracted data with versioning and JSONB storage
    crawl_attempts  — Every crawl attempt including failures (audit trail)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arachne_models.db.database import Base


class JobRow(Base):
    """jobs table — tracks every scrape request.

    Lifecycle: pending → queued → running → completed/failed/cancelled

    JSONB columns (extraction_schema, metadata) provide flexible schema
    without MongoDB — full SQL power + flexible document storage.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal"
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # JSONB columns — flexible schema (replaces need for MongoDB)
    extraction_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    # Claim-Check references (MinIO object IDs)
    raw_html_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    entities: Mapped[list[EntityRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    crawl_attempts: Mapped[list[CrawlAttemptRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','queued','running','completed','failed','cancelled')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "priority IN ('low','normal','high','critical')",
            name="ck_jobs_priority",
        ),
        CheckConstraint("char_length(url) <= 2048", name="ck_jobs_url_length"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created", "created_at"),
        Index("ix_jobs_priority_status", "priority", "status"),
    )


class EntityRow(Base):
    """entities table — extracted data with versioning.

    JSONB `data` column with GIN index enables flexible queries like:
        WHERE data->>'price' > '100'

    This replaces the need for MongoDB — PostgreSQL JSONB provides
    document-store flexibility with full SQL power (joins, transactions,
    constraints).
    """

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_html_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    job: Mapped[JobRow] = relationship(back_populates="entities")

    __table_args__ = (
        UniqueConstraint("job_id", "entity_type", "version", name="uq_entity_version"),
        Index("ix_entities_job", "job_id"),
        Index("ix_entities_type", "entity_type"),
        Index("ix_entities_data", "data", postgresql_using="gin"),
    )


class CrawlAttemptRow(Base):
    """crawl_attempts table — every crawl attempt including failures.

    Full audit trail: every HTTP request, its status code, timing,
    proxy used, and any errors. Essential for debugging anti-bot
    escalation in Phase 2.
    """

    __tablename__ = "crawl_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxy_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_html_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    job: Mapped[JobRow] = relationship(back_populates="crawl_attempts")

    __table_args__ = (
        Index("ix_crawl_attempts_job", "job_id"),
    )
