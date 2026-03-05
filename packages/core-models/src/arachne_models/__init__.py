"""
arachne_models — Shared data contracts for the Arachne platform.

This package is the single source of truth for all data shapes flowing
through the system. Every service imports from here instead of defining
its own models, which eliminates schema drift between services.

Usage:
    from arachne_models.jobs import Job, JobCreate, JobStatus
    from arachne_models.crawl import CrawlRequest, CrawlResult
    from arachne_models.events import CrawlRequestEvent, CrawlResultEvent
    from arachne_models.extraction import ExtractionResult, FieldConfig
"""

from arachne_models.jobs import Job, JobCreate, JobPriority, JobStatus
from arachne_models.crawl import CrawlRequest, CrawlResult
from arachne_models.events import (
    CrawlRequestEvent,
    CrawlResultEvent,
    ExtractionRequestEvent,
    ExtractionResultEvent,
)
from arachne_models.extraction import ExtractionResult, ExtractionSchema, FieldConfig

__all__ = [
    # Jobs
    "Job",
    "JobCreate",
    "JobStatus",
    "JobPriority",
    # Crawl
    "CrawlRequest",
    "CrawlResult",
    # Events
    "CrawlRequestEvent",
    "CrawlResultEvent",
    "ExtractionRequestEvent",
    "ExtractionResultEvent",
    # Extraction
    "ExtractionResult",
    "ExtractionSchema",
    "FieldConfig",
]
