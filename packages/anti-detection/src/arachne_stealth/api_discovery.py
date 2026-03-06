"""
API reverse engineering — discover hidden APIs via network interception.

During browser sessions, many modern websites load data from internal
JSON APIs (React SPAs, infinite scroll, product catalogs). By intercepting
these network requests, we can discover the underlying APIs and replay
them directly with curl_cffi — bypassing HTML parsing entirely.

This is the ultimate de-escalation: once an API is discovered, we can
fetch structured data at HTTP speed without any anti-bot overhead, as
APIs often have weaker or no anti-bot protection.

Research ref: Research.md §1.9 — Hidden API discovery strategy
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredAPI:
    """A discovered internal API endpoint."""
    url: str
    method: str = "GET"
    content_type: str = "application/json"
    domain: str = ""

    # Request analysis
    required_headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    auth_required: bool = False
    auth_type: str = ""  # "bearer", "cookie", "api_key", etc.

    # Response analysis
    response_content_type: str = ""
    has_pagination: bool = False
    pagination_type: str = ""  # "offset", "cursor", "page"
    sample_response_size: int = 0

    # Reproducibility
    reproduced: bool = False
    reproduction_status: int = 0

    @property
    def endpoint_path(self) -> str:
        """Extract just the path from the URL."""
        return urlparse(self.url).path


@dataclass
class APIDiscoveryReport:
    """Summary of discovered APIs for a domain."""
    domain: str
    total_requests_captured: int = 0
    json_endpoints: list[DiscoveredAPI] = field(default_factory=list)
    graphql_endpoints: list[DiscoveredAPI] = field(default_factory=list)
    other_api_endpoints: list[DiscoveredAPI] = field(default_factory=list)

    @property
    def total_apis_found(self) -> int:
        return len(self.json_endpoints) + len(self.graphql_endpoints) + len(self.other_api_endpoints)


# =============================================================================
# Patterns for identifying API requests vs. static resources
# =============================================================================

# URL patterns that indicate API endpoints
_API_PATH_PATTERNS = [
    r"/api/",
    r"/v[0-9]+/",
    r"/graphql",
    r"/query",
    r"/search",
    r"/data",
    r"\.json$",
]

# URL patterns to ignore (static resources, analytics, ads)
_IGNORE_PATTERNS = [
    r"\.(css|js|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)(\?|$)",
    r"google-analytics\.com",
    r"googletagmanager\.com",
    r"facebook\.net",
    r"doubleclick\.net",
    r"amazonaws\.com/analytics",
    r"sentry\.io",
    r"hotjar\.com",
    r"segment\.io",
    r"intercom\.io",
]

# Pagination indicators
_PAGINATION_PATTERNS = {
    "offset": [r"offset=", r"skip=", r"start="],
    "cursor": [r"cursor=", r"after=", r"before=", r"next_token="],
    "page": [r"page=", r"pageNumber=", r"p="],
}


def analyze_network_requests(
    requests: list[dict[str, Any]],
    domain: str = "",
) -> APIDiscoveryReport:
    """Analyze captured network requests to discover APIs.

    Filters out static resources, identifies JSON/GraphQL endpoints,
    detects pagination patterns, and produces a discovery report.

    Args:
        requests: List of captured network request dicts (from browser CDP).
        domain: Source domain for the report.

    Returns:
        APIDiscoveryReport with categorized discovered APIs.
    """
    report = APIDiscoveryReport(
        domain=domain,
        total_requests_captured=len(requests),
    )

    for req in requests:
        url = req.get("url", "")
        method = req.get("method", "GET")
        status = req.get("status", 0)
        mime_type = req.get("mime_type", "")
        response_headers = req.get("headers", {})

        # Skip non-successful responses
        if status < 200 or status >= 400:
            continue

        # Skip ignored patterns (analytics, ads, static resources)
        if any(re.search(pat, url, re.IGNORECASE) for pat in _IGNORE_PATTERNS):
            continue

        # Identify JSON API endpoints
        is_json = "json" in mime_type or "json" in url.lower()

        # Identify GraphQL
        is_graphql = "graphql" in url.lower()

        # Identify other API patterns
        is_api = any(re.search(pat, url, re.IGNORECASE) for pat in _API_PATH_PATTERNS)

        if not (is_json or is_graphql or is_api):
            continue

        # Analyze the discovered endpoint
        api = DiscoveredAPI(
            url=url,
            method=method,
            domain=domain,
            response_content_type=mime_type,
            sample_response_size=req.get("response_size", 0),
        )

        # Detect authentication requirements
        if "authorization" in {k.lower() for k in response_headers}:
            api.auth_required = True
            auth_value = response_headers.get("authorization", "")
            if auth_value.startswith("Bearer"):
                api.auth_type = "bearer"
            elif auth_value.startswith("Basic"):
                api.auth_type = "basic"
            else:
                api.auth_type = "custom"

        # Detect pagination
        for pagination_type, patterns in _PAGINATION_PATTERNS.items():
            if any(re.search(pat, url, re.IGNORECASE) for pat in patterns):
                api.has_pagination = True
                api.pagination_type = pagination_type
                break

        # Categorize
        if is_graphql:
            report.graphql_endpoints.append(api)
        elif is_json:
            report.json_endpoints.append(api)
        else:
            report.other_api_endpoints.append(api)

    logger.info(
        f"API discovery for {domain}: "
        f"{len(report.json_endpoints)} JSON, "
        f"{len(report.graphql_endpoints)} GraphQL, "
        f"{len(report.other_api_endpoints)} other "
        f"(from {len(requests)} total requests)"
    )

    return report


async def reproduce_api(
    api: DiscoveredAPI,
    cookies: dict[str, str] | None = None,
) -> bool:
    """Test if a discovered API can be reproduced with curl_cffi.

    Makes the same request using StealthHttpClient and verifies
    that the API returns valid data without browser context.

    Args:
        api: Discovered API endpoint.
        cookies: Optional cookies to include (from browser session).

    Returns:
        True if the API was successfully reproduced.
    """
    from arachne_stealth.http_client import StealthHttpClient

    client = StealthHttpClient()
    try:
        result = await client.fetch(
            api.url,
            headers=api.required_headers or None,
            cookies=cookies,
            session_key=f"_reproduce_{api.domain}",
        )

        success = 200 <= result.status_code < 400
        api.reproduced = success
        api.reproduction_status = result.status_code

        if success:
            logger.info(f"API reproduced: {api.url} → {result.status_code}")
        else:
            logger.warning(f"API reproduction failed: {api.url} → {result.status_code}")

        return success

    except Exception as e:
        logger.warning(f"API reproduction error: {api.url} → {e}")
        api.reproduced = False
        return False
    finally:
        await client.close_all()
