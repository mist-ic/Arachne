"""
MinIO client wrapper implementing the Claim-Check pattern.

The Claim-Check pattern (from Enterprise Integration Patterns):
    1. Store the large payload in external storage (MinIO)
    2. Pass only a small reference ("claim check") through the message broker
    3. Consumer retrieves the payload using the reference

This keeps Redpanda messages small (<1MB) while supporting pages that can
be 500KB-5MB of raw HTML.

Reference format: "minio://{bucket}/{object_path}"
Example: "minio://arachne-raw-html/raw/550e8400-e29b/2026-03-05T22:00:00.html"
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone

from minio import Minio

from arachne_storage.buckets import Bucket

logger = logging.getLogger(__name__)


class ArachneStorage:
    """Claim-Check storage client for MinIO.

    Provides typed methods for storing and retrieving different payload types
    (raw HTML, extracted results, screenshots, artifacts). Each method handles
    content type, path conventions, and reference generation.

    Args:
        endpoint: MinIO server address (host:port).
        access_key: MinIO access key.
        secret_key: MinIO secret key.
        secure: Use HTTPS (False for local dev).
    """

    def __init__(
        self,
        endpoint: str = "localhost:9000",
        access_key: str = "arachne",
        secret_key: str = "arachne123",
        secure: bool = False,
    ) -> None:
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    # -------------------------------------------------------------------------
    # Store operations — return a reference string ("claim check")
    # -------------------------------------------------------------------------

    def store_raw_html(self, job_id: str, html: str) -> str:
        """Store raw HTML and return a MinIO reference.

        Path convention: raw/{job_id}/{timestamp}.html

        Args:
            job_id: UUID of the job.
            html: Raw HTML content.

        Returns:
            Reference string like "minio://arachne-raw-html/raw/{job_id}/{ts}.html"
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        object_name = f"raw/{job_id}/{timestamp}.html"

        data = html.encode("utf-8")
        self.client.put_object(
            bucket_name=Bucket.RAW_HTML,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type="text/html; charset=utf-8",
        )

        ref = f"minio://{Bucket.RAW_HTML}/{object_name}"
        logger.debug("Stored raw HTML", extra={"ref": ref, "size": len(data)})
        return ref

    def store_result(self, job_id: str, data: dict) -> str:
        """Store extracted result data as JSON.

        Path convention: results/{job_id}/{timestamp}.json

        Args:
            job_id: UUID of the job.
            data: Extracted data dictionary.

        Returns:
            Reference string like "minio://arachne-results/results/{job_id}/{ts}.json"
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        object_name = f"results/{job_id}/{timestamp}.json"

        payload = json.dumps(data, default=str).encode("utf-8")
        self.client.put_object(
            bucket_name=Bucket.RESULTS,
            object_name=object_name,
            data=io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )

        ref = f"minio://{Bucket.RESULTS}/{object_name}"
        logger.debug("Stored result", extra={"ref": ref, "size": len(payload)})
        return ref

    def store_screenshot(self, job_id: str, png_data: bytes) -> str:
        """Store a page screenshot (PNG).

        Path convention: screenshots/{job_id}/{timestamp}.png

        Args:
            job_id: UUID of the job.
            png_data: Raw PNG bytes.

        Returns:
            Reference string.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        object_name = f"screenshots/{job_id}/{timestamp}.png"

        self.client.put_object(
            bucket_name=Bucket.SCREENSHOTS,
            object_name=object_name,
            data=io.BytesIO(png_data),
            length=len(png_data),
            content_type="image/png",
        )

        return f"minio://{Bucket.SCREENSHOTS}/{object_name}"

    # -------------------------------------------------------------------------
    # Retrieve operation — resolve a reference back to content
    # -------------------------------------------------------------------------

    def retrieve(self, ref: str) -> bytes:
        """Retrieve object content by its minio:// reference.

        Parses the reference to extract bucket and object path,
        then downloads the object.

        Args:
            ref: Reference string like "minio://bucket-name/path/to/object"

        Returns:
            Raw bytes of the object.

        Raises:
            ValueError: If the reference format is invalid.
        """
        bucket, object_name = self._parse_ref(ref)
        response = self.client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def retrieve_text(self, ref: str) -> str:
        """Retrieve object content as UTF-8 text.

        Convenience wrapper around retrieve() for HTML and JSON.
        """
        return self.retrieve(ref).decode("utf-8")

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        """Parse a minio:// reference into (bucket, object_name).

        Args:
            ref: "minio://bucket-name/path/to/object"

        Returns:
            Tuple of (bucket_name, object_path).
        """
        if not ref.startswith("minio://"):
            raise ValueError(f"Invalid MinIO reference (must start with minio://): {ref}")

        path = ref[len("minio://"):]
        bucket, _, object_name = path.partition("/")

        if not bucket or not object_name:
            raise ValueError(f"Invalid MinIO reference (missing bucket or path): {ref}")

        return bucket, object_name
