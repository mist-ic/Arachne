"""Initial schema: jobs, entities, crawl_attempts

Revision ID: 0001
Revises: None
Create Date: 2026-03-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Jobs table ---
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extraction_schema", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("raw_html_ref", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','queued','running','completed','failed','cancelled')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low','normal','high','critical')",
            name="ck_jobs_priority",
        ),
        sa.CheckConstraint("char_length(url) <= 2048", name="ck_jobs_url_length"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created", "jobs", ["created_at"])
    op.create_index("ix_jobs_priority_status", "jobs", ["priority", "status"])

    # --- Entities table ---
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_html_ref", sa.Text(), nullable=True),
        sa.Column("schema_hash", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("job_id", "entity_type", "version", name="uq_entity_version"),
    )
    op.create_index("ix_entities_job", "entities", ["job_id"])
    op.create_index("ix_entities_type", "entities", ["entity_type"])
    op.create_index("ix_entities_data", "entities", ["data"], postgresql_using="gin")

    # --- Crawl attempts table ---
    op.create_table(
        "crawl_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("proxy_used", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_html_ref", sa.Text(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_crawl_attempts_job", "crawl_attempts", ["job_id"])


def downgrade() -> None:
    op.drop_table("crawl_attempts")
    op.drop_table("entities")
    op.drop_table("jobs")
