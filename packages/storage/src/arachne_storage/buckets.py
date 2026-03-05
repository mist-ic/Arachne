"""
Bucket definitions — single source of truth for all MinIO bucket names.

These must match the buckets created by the minio-init container
in infra/docker-compose.yml.
"""

from __future__ import annotations

from enum import StrEnum


class Bucket(StrEnum):
    """MinIO bucket names used by Arachne."""

    RAW_HTML = "arachne-raw-html"
    SCREENSHOTS = "arachne-screenshots"
    RESULTS = "arachne-results"
    ARTIFACTS = "arachne-artifacts"
