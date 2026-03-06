"""
Temporal activities for stealth browser-based fetching.

These activities handle jobs that failed at the HTTP tier (worker-http)
and have been escalated by the Evasion Router to use a browser backend.

Activities:
    fetch_with_browser   — Navigate to URL using a stealth browser
    export_cookies       — Export browser cookies for HTTP handoff
    update_job_status    — Update job status in PostgreSQL (shared)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)


@dataclass
class BrowserFetchResult:
    """Output of the fetch_with_browser activity."""
    html: str
    status_code: int
    headers: dict[str, str]
    elapsed_ms: int
    backend_used: str
    cookies: list[dict[str, Any]]
    network_requests: list[dict[str, Any]]


@dataclass
class CookieExportResult:
    """Output of the export_cookies activity."""
    cookies: list[dict[str, Any]]
    domain: str
    count: int


@activity.defn
async def fetch_with_browser(
    url: str,
    backend_name: str = "camoufox",
    headless: bool = True,
    wait_for: str | None = None,
    proxy: str | None = None,
) -> BrowserFetchResult:
    """Navigate to a URL using a stealth browser backend.

    This activity is called when the Evasion Router escalates beyond
    HTTP-only fetching. It launches a full browser session, navigates
    to the URL, and returns the page content along with cookies for
    potential de-escalation back to HTTP.

    The backend is selected based on the domain's anti-bot vendor:
        - Camoufox: Default for most sites (highest general stealth)
        - Pydoll: Used for Cloudflare-protected sites (Turnstile auto-solve)

    Args:
        url: Target URL to fetch.
        backend_name: Browser backend to use ("camoufox" or "pydoll").
        headless: Run browser in headless mode.
        wait_for: Optional CSS selector to wait for.
        proxy: Optional proxy URL.

    Returns:
        BrowserFetchResult with HTML, cookies, network requests, and timing.
    """
    from arachne_stealth.browser_backend import BrowserBackend

    backend = _create_backend(backend_name)

    activity.logger.info(
        f"Stealth fetch with {backend.name} — {url}"
    )

    try:
        await backend.launch(headless=headless, proxy=proxy)
        result = await backend.navigate(url, wait_for=wait_for)

        # Serialize cookies for Temporal
        cookies_data = [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires,
                "http_only": c.http_only,
                "secure": c.secure,
                "same_site": c.same_site,
            }
            for c in result.cookies
        ]

        activity.logger.info(
            f"Stealth fetch complete — {backend.name} — {url} — "
            f"{result.status_code} in {result.elapsed_ms}ms — "
            f"{len(cookies_data)} cookies — "
            f"{len(result.network_requests)} network requests"
        )

        return BrowserFetchResult(
            html=result.html,
            status_code=result.status_code,
            headers=result.headers,
            elapsed_ms=result.elapsed_ms,
            backend_used=backend.name,
            cookies=cookies_data,
            network_requests=result.network_requests,
        )

    finally:
        await backend.close()


@activity.defn
async def store_browser_cookies(
    job_id: str,
    domain: str,
    cookies: list[dict[str, Any]],
) -> CookieExportResult:
    """Store browser cookies for future HTTP handoff.

    After a successful browser fetch, cookies (especially Cloudflare
    CF clearance) are stored so that subsequent requests to the same
    domain can use fast HTTP with curl_cffi instead of a full browser.

    Args:
        job_id: UUID string of the job.
        domain: Target domain the cookies belong to.
        cookies: List of cookie dicts from browser.

    Returns:
        CookieExportResult with count and domain.
    """
    activity.logger.info(
        f"Stored {len(cookies)} cookies for domain {domain} (job {job_id})"
    )

    return CookieExportResult(
        cookies=cookies,
        domain=domain,
        count=len(cookies),
    )


def _create_backend(name: str):
    """Factory function to create browser backends by name."""
    if name == "camoufox":
        from arachne_stealth.backends.camoufox_backend import CamoufoxBackend
        return CamoufoxBackend()
    elif name == "pydoll":
        from arachne_stealth.backends.pydoll_backend import PydollBackend
        return PydollBackend()
    else:
        raise ValueError(
            f"Unknown browser backend: {name}. "
            f"Supported: 'camoufox', 'pydoll'"
        )
