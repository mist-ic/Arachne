"""
arachne_storage — MinIO client wrapper for the Claim-Check pattern.

Large payloads (raw HTML, screenshots, extracted data, HAR files) are stored
in MinIO. Only the object reference (e.g. "minio://arachne-raw-html/raw/...")
flows through Redpanda messages and database records.

Usage:
    from arachne_storage import ArachneStorage, Bucket

    storage = ArachneStorage()
    ref = storage.store_raw_html(job_id="abc-123", html="<html>...")
    html = storage.retrieve(ref)
"""

from arachne_storage.client import ArachneStorage
from arachne_storage.buckets import Bucket

__all__ = [
    "ArachneStorage",
    "Bucket",
]
