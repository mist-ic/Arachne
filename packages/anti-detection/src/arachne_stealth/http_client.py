"""
Stealth HTTP client — curl_cffi wrapper with browser-identical TLS fingerprints.

curl_cffi uses the `impersonate` parameter to replicate exact browser TLS
ClientHello signatures (JA4), HTTP/2 SETTINGS frames, and header ordering.
This makes HTTP requests indistinguishable from real browser traffic at the
TLS/network layer — the single most impactful anti-detection upgrade.

The StealthHttpClient wraps curl_cffi's AsyncSession with:
    - Browser profile rotation (profiles.py)
    - Consistent profile per session/domain
    - Cookie jar management for session persistence
    - Same FetchResult output format as Phase 1

Research ref: Research.md §1.2 — curl_cffi is the consensus #1 choice across
all three research agents for TLS fingerprint spoofing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from curl_cffi.requests import AsyncSession, Response

from arachne_stealth.profiles import BrowserProfile, ProfileRotator

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Output of a stealth HTTP fetch.

    Same structure as Phase 1's FetchResult from worker-http/activities.py,
    ensuring backward compatibility.
    """
    html: str
    status_code: int
    headers: dict[str, str]
    elapsed_ms: int
    profile_used: str = ""


class StealthHttpClient:
    """HTTP client with browser-identical TLS/JA4 fingerprints.

    Wraps curl_cffi's AsyncSession to produce requests that are
    indistinguishable from real browser traffic at the TLS and HTTP/2 layer.

    The client rotates browser profiles across sessions but maintains
    consistency within a session (identified by domain). This prevents
    fingerprint tracking across sessions while avoiding the inconsistency
    of switching browser identity mid-session.

    Args:
        profile_rotator: Optional ProfileRotator instance. If None, a
                         default rotator with all profiles is used.
        proxy: Optional proxy URL (http://user:pass@host:port).
        timeout: Request timeout in seconds.

    Usage:
        client = StealthHttpClient()
        result = await client.fetch("https://example.com")
        print(result.status_code, result.profile_used)
    """

    def __init__(
        self,
        profile_rotator: ProfileRotator | None = None,
        proxy: str | None = None,
        timeout: float = 25.0,
    ) -> None:
        self._rotator = profile_rotator or ProfileRotator()
        self._proxy = proxy
        self._timeout = timeout
        self._sessions: dict[str, AsyncSession] = {}

    async def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        session_key: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a URL with browser-identical TLS fingerprints.

        Args:
            url: Target URL to fetch.
            headers: Optional extra headers (merged with profile headers).
            session_key: Domain/session key for profile consistency.
                         If None, the domain is extracted from the URL.
            cookies: Optional cookies to include in the request.

        Returns:
            FetchResult with HTML, status code, headers, timing, and profile.

        Raises:
            curl_cffi.requests.errors.RequestsError: On network/timeout errors.
        """
        # Determine session key from URL domain if not provided
        if session_key is None:
            from urllib.parse import urlparse
            session_key = urlparse(url).netloc

        # Select a profile for this session
        profile = self._rotator.select(session_key)

        # Build request headers — profile headers first, then overrides
        request_headers = profile.build_headers()
        if headers:
            request_headers.update(headers)

        logger.debug(
            "Stealth fetch",
            extra={"url": url, "profile": profile.name, "impersonate": profile.impersonate},
        )

        start = perf_counter()

        # Get or create a session for this key
        session = await self._get_session(session_key, profile)

        response: Response = await session.get(
            url,
            headers=request_headers,
            cookies=cookies,
            timeout=self._timeout,
            allow_redirects=True,
        )

        elapsed_ms = int((perf_counter() - start) * 1000)

        logger.debug(
            "Stealth fetch complete",
            extra={
                "url": url,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
                "profile": profile.name,
            },
        )

        return FetchResult(
            html=response.text,
            status_code=response.status_code,
            headers=dict(response.headers),
            elapsed_ms=elapsed_ms,
            profile_used=profile.name,
        )

    async def _get_session(
        self,
        session_key: str,
        profile: BrowserProfile,
    ) -> AsyncSession:
        """Get or create an AsyncSession for a given session key.

        Sessions are cached per key to maintain cookie state and
        connection pooling within a session.
        """
        if session_key not in self._sessions:
            self._sessions[session_key] = AsyncSession(
                impersonate=profile.impersonate,
                proxy=self._proxy,
            )
        return self._sessions[session_key]

    async def close_session(self, session_key: str) -> None:
        """Close and remove a specific session."""
        session = self._sessions.pop(session_key, None)
        if session:
            session.close()

    async def close_all(self) -> None:
        """Close all open sessions."""
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

    def get_session_cookies(self, session_key: str) -> dict[str, str]:
        """Export cookies from a session (for Browser→HTTP handoff).

        Args:
            session_key: The session to export cookies from.

        Returns:
            Dict of cookie name → value.
        """
        session = self._sessions.get(session_key)
        if not session or not session.cookies:
            return {}

        return {
            cookie.name: cookie.value
            for cookie in session.cookies
            if cookie.value is not None
        }

    def inject_cookies(
        self,
        session_key: str,
        cookies: dict[str, str],
    ) -> None:
        """Inject cookies into a session (from browser handoff).

        Args:
            session_key: Target session.
            cookies: Dict of cookie name → value to inject.
        """
        session = self._sessions.get(session_key)
        if session:
            for name, value in cookies.items():
                session.cookies.set(name, value)
