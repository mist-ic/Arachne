"""
Topic configuration — the single source of truth for all Redpanda topics.

Each topic is defined once here with its name, partition count, and retention.
The init-topics.py script reads this config to auto-create topics on startup.
Services reference TOPICS["crawl.requests"] rather than hardcoding strings.

Topic design:
    All topics are keyed by job_id, which ensures ordered processing per job.
    Messages for the same job always land on the same partition.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicConfig:
    """Immutable topic definition."""

    name: str
    partitions: int = 6
    retention_ms: int = 7 * 24 * 60 * 60 * 1000  # 7 days default


# Central topic registry — every topic in the system
TOPICS: dict[str, TopicConfig] = {
    "crawl.requests": TopicConfig(
        name="crawl.requests",
        partitions=6,
    ),
    "crawl.results": TopicConfig(
        name="crawl.results",
        partitions=6,
    ),
    "extraction.requests": TopicConfig(
        name="extraction.requests",
        partitions=6,
    ),
    "extraction.results": TopicConfig(
        name="extraction.results",
        partitions=6,
    ),
    "job.status": TopicConfig(
        name="job.status",
        partitions=3,  # Fewer partitions — lower throughput, just status updates
    ),
}
