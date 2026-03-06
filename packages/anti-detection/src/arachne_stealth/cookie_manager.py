"""
Cookie and session state management for Browser→HTTP handoff.

Manages per-domain cookie storage, transfer between browser contexts
and curl_cffi sessions, TTL tracking, and session rotation.

This is the glue that makes the de-escalation path work: browser obtains
clearance cookies → cookies transferred to HTTP client → 10-20+ fast
HTTP requests with those cookies → re-escalate briefly when cookies expire.

Research ref: Research.md §1.6 — Browser → HTTP Handoff Pattern
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from arachne_stealth.browser_backend import Cookie

logger = logging.getLogger(__name__)


@dataclass
class CookieJar:
    """Per-domain cookie storage with TTL tracking.

    Attributes:
        domain: The domain these cookies belong to.
        cookies: List of Cookie objects.
        obtained_at: Unix timestamp when cookies were obtained.
        estimated_ttl: Estimated time-to-live in seconds.
        source: How cookies were obtained ("browser", "api", etc.).
        refresh_count: How many times cookies have been refreshed.
    """
    domain: str
    cookies: list[Cookie] = field(default_factory=list)
    obtained_at: float = field(default_factory=time.time)
    estimated_ttl: float = 1800.0  # 30 minutes default
    source: str = "browser"
    refresh_count: int = 0

    @property
    def age_seconds(self) -> float:
        """How old these cookies are in seconds."""
        return time.time() - self.obtained_at

    @property
    def is_expired(self) -> bool:
        """Whether cookies have exceeded their estimated TTL."""
        return self.age_seconds > self.estimated_ttl

    @property
    def is_expiring_soon(self) -> bool:
        """Whether cookies will expire within 20% of their TTL.

        Used for proactive refresh — re-escalate to browser before
        cookies actually expire, preventing a failed request.
        """
        return self.age_seconds > (self.estimated_ttl * 0.8)

    def to_dict(self) -> dict[str, str]:
        """Convert cookies to a simple name→value dict for curl_cffi."""
        return {c.name: c.value for c in self.cookies}

    def to_list(self) -> list[dict[str, Any]]:
        """Convert cookies to a serializable list of dicts."""
        return [
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
            for c in self.cookies
        ]


class CookieManager:
    """Cross-tier cookie and session state management.

    Manages the cookie lifecycle across browser and HTTP tiers:
        1. Browser obtains cookies (CF clearance, session tokens)
        2. CookieManager stores them per-domain with TTL
        3. StealthHttpClient injects them for fast HTTP requests
        4. On expiration/challenge, triggers re-escalation to browser
        5. Browser refreshes cookies, repeat

    This is what makes the Evasion Router production-practical — without
    cookie management, every request to a protected site requires a full
    browser session.
    """

    def __init__(self) -> None:
        self._jars: dict[str, CookieJar] = {}

    def store(
        self,
        domain: str,
        cookies: list[Cookie],
        source: str = "browser",
        estimated_ttl: float = 1800.0,
    ) -> None:
        """Store cookies for a domain.

        Args:
            domain: Target domain.
            cookies: List of Cookie objects from browser.
            source: How cookies were obtained.
            estimated_ttl: Estimated validity in seconds.
        """
        existing = self._jars.get(domain)
        refresh_count = (existing.refresh_count + 1) if existing else 0

        self._jars[domain] = CookieJar(
            domain=domain,
            cookies=cookies,
            source=source,
            estimated_ttl=estimated_ttl,
            refresh_count=refresh_count,
        )

        logger.info(
            f"Stored {len(cookies)} cookies for {domain} "
            f"(TTL={estimated_ttl}s, refresh #{refresh_count})"
        )

    def get(self, domain: str) -> CookieJar | None:
        """Get the cookie jar for a domain, or None if not stored."""
        return self._jars.get(domain)

    def get_valid_cookies(self, domain: str) -> dict[str, str] | None:
        """Get valid (non-expired) cookies as a dict for curl_cffi.

        Returns None if no cookies exist or they're expired.
        Logs a warning if cookies are expiring soon.
        """
        jar = self._jars.get(domain)
        if jar is None:
            return None

        if jar.is_expired:
            logger.info(f"Cookies expired for {domain} (age={jar.age_seconds:.0f}s)")
            return None

        if jar.is_expiring_soon:
            logger.warning(
                f"Cookies expiring soon for {domain} "
                f"(age={jar.age_seconds:.0f}s / TTL={jar.estimated_ttl:.0f}s)"
            )

        return jar.to_dict()

    def needs_refresh(self, domain: str) -> bool:
        """Check if cookies need refreshing (expired or expiring soon)."""
        jar = self._jars.get(domain)
        if jar is None:
            return True
        return jar.is_expired or jar.is_expiring_soon

    def invalidate(self, domain: str) -> None:
        """Invalidate cookies for a domain (e.g., on 403 response)."""
        if domain in self._jars:
            logger.info(f"Invalidated cookies for {domain}")
            del self._jars[domain]

    def clear_all(self) -> None:
        """Clear all stored cookies."""
        self._jars.clear()

    @property
    def domains(self) -> list[str]:
        """List all domains with stored cookies."""
        return list(self._jars.keys())

    def stats(self) -> dict[str, Any]:
        """Get cookie manager statistics."""
        return {
            "total_domains": len(self._jars),
            "domains": {
                domain: {
                    "cookie_count": len(jar.cookies),
                    "age_seconds": round(jar.age_seconds),
                    "ttl_seconds": jar.estimated_ttl,
                    "expired": jar.is_expired,
                    "expiring_soon": jar.is_expiring_soon,
                    "source": jar.source,
                    "refresh_count": jar.refresh_count,
                }
                for domain, jar in self._jars.items()
            },
        }
