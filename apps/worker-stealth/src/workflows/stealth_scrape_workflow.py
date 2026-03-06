"""
StealthScrapeWorkflow — Temporal workflow for browser-based stealth fetching.

Handles jobs that have been escalated from worker-http by the Evasion Router.
Uses stealth browser backends (Camoufox, Pydoll) to bypass anti-bot protection,
then feeds results back into the same downstream pipeline (MinIO, extraction,
PostgreSQL).

The workflow also supports de-escalation: after obtaining clearance cookies
via browser, it exports them so future requests to the same domain can
use fast HTTP via curl_cffi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        BrowserFetchResult,
        CookieExportResult,
        fetch_with_browser,
        store_browser_cookies,
    )


@dataclass
class StealthScrapeParams:
    """Input parameters for the stealth scrape workflow."""
    job_id: str
    url: str
    backend_name: str = "camoufox"
    headless: bool = True
    wait_for: str | None = None
    proxy: str | None = None
    extraction_schema: dict | None = None


@dataclass
class StealthScrapeResult:
    """Output of a completed stealth scrape workflow."""
    job_id: str
    url: str
    success: bool
    raw_html_ref: str | None = None
    result_ref: str | None = None
    backend_used: str = ""
    cookies_exported: int = 0
    api_endpoints_found: int = 0
    elapsed_ms: int = 0
    error: str | None = None


@workflow.defn
class StealthScrapeWorkflow:
    """Durable workflow for stealth browser-based scraping.

    This workflow runs on the "scrape-stealth" task queue and handles
    jobs that were escalated from worker-http due to anti-bot blocking.

    Steps:
        1. Launch browser backend (Camoufox or Pydoll)
        2. Navigate to URL (with optional Turnstile auto-solve)
        3. Export cookies for Browser→HTTP handoff
        4. Store raw HTML in MinIO
        5. Update job status in PostgreSQL
    """

    @workflow.run
    async def run(self, params: StealthScrapeParams) -> StealthScrapeResult:
        """Execute the stealth scrape pipeline."""

        try:
            # --- Step 1: Fetch with browser ---
            fetch_result: BrowserFetchResult = await workflow.execute_activity(
                fetch_with_browser,
                args=[
                    params.url,
                    params.backend_name,
                    params.headless,
                    params.wait_for,
                    params.proxy,
                ],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            workflow.logger.info(
                f"Browser fetch complete — {fetch_result.backend_used} — "
                f"{fetch_result.status_code} in {fetch_result.elapsed_ms}ms"
            )

            # --- Step 2: Export cookies for HTTP handoff ---
            from urllib.parse import urlparse
            domain = urlparse(params.url).netloc

            cookie_result: CookieExportResult = await workflow.execute_activity(
                store_browser_cookies,
                args=[params.job_id, domain, fetch_result.cookies],
                start_to_close_timeout=timedelta(seconds=5),
            )

            workflow.logger.info(
                f"Exported {cookie_result.count} cookies for {domain}"
            )

            # --- Step 3: Store raw HTML in MinIO ---
            # Re-use the store_raw_html activity from worker-http
            # Import it at workflow level to avoid circular deps
            from activities import store_browser_cookies  # already imported

            # We need to store the HTML — use a simple inline approach
            # since we can't import from worker-http easily
            raw_html_ref = None
            if fetch_result.html:
                from arachne_storage import ArachneStorage
                storage = ArachneStorage()
                raw_html_ref = storage.store_raw_html(params.job_id, fetch_result.html)

            return StealthScrapeResult(
                job_id=params.job_id,
                url=params.url,
                success=True,
                raw_html_ref=raw_html_ref,
                backend_used=fetch_result.backend_used,
                cookies_exported=cookie_result.count,
                api_endpoints_found=len(fetch_result.network_requests),
                elapsed_ms=fetch_result.elapsed_ms,
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            workflow.logger.error(
                f"Stealth workflow failed for job {params.job_id}: {error_msg}"
            )

            return StealthScrapeResult(
                job_id=params.job_id,
                url=params.url,
                success=False,
                error=error_msg,
            )
