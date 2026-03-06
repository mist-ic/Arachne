"""
Browser fingerprint profiles for TLS/HTTP impersonation.

Each profile defines the curl_cffi impersonate target, matching User-Agent,
Accept headers, and HTTP/2 settings. curl_cffi uses these to produce
browser-identical TLS ClientHello (JA4) and HTTP/2 fingerprints.

Profiles are rotated ACROSS sessions (different identities) but kept
CONSISTENT WITHIN a session (one identity per cookie jar).

Research ref: Research.md §1.2 — JA4+ fingerprinting and curl_cffi
impersonate targets.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum


class BrowserFamily(StrEnum):
    """Supported browser families for impersonation."""
    CHROME = "chrome"
    FIREFOX = "firefox"
    SAFARI = "safari"
    EDGE = "edge"


@dataclass(frozen=True)
class BrowserProfile:
    """A complete browser fingerprint profile.

    Attributes:
        name: Human-readable name (e.g. "Chrome 131 Windows").
        family: Browser family (chrome, firefox, safari, edge).
        impersonate: curl_cffi impersonate string (e.g. "chrome131").
        user_agent: Matching User-Agent header string.
        accept: Accept header value for HTML requests.
        accept_language: Accept-Language header value.
        accept_encoding: Accept-Encoding header value.
        sec_ch_ua: Sec-CH-UA header (Chromium-based only).
        sec_ch_ua_platform: Sec-CH-UA-Platform header.
        platform: OS platform string for consistency checks.
        weight: Selection weight (higher = more common in the wild).
    """
    name: str
    family: BrowserFamily
    impersonate: str
    user_agent: str
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.9"
    accept_encoding: str = "gzip, deflate, br, zstd"
    sec_ch_ua: str | None = None
    sec_ch_ua_platform: str | None = None
    platform: str = "Windows"
    weight: int = 10

    def build_headers(self) -> dict[str, str]:
        """Build a complete set of browser-realistic request headers.

        Returns headers in the correct order for the browser family.
        Header ordering is part of the JA4H fingerprint — wrong order
        leaks that this isn't a real browser.
        """
        headers: dict[str, str] = {}

        if self.family in (BrowserFamily.CHROME, BrowserFamily.EDGE):
            # Chromium header order: sec-ch-ua → sec-ch-ua-mobile →
            # sec-ch-ua-platform → Upgrade-Insecure-Requests → User-Agent →
            # Accept → ...
            if self.sec_ch_ua:
                headers["sec-ch-ua"] = self.sec_ch_ua
                headers["sec-ch-ua-mobile"] = "?0"
            if self.sec_ch_ua_platform:
                headers["sec-ch-ua-platform"] = self.sec_ch_ua_platform
            headers["Upgrade-Insecure-Requests"] = "1"
            headers["User-Agent"] = self.user_agent
            headers["Accept"] = self.accept
            headers["Accept-Encoding"] = self.accept_encoding
            headers["Accept-Language"] = self.accept_language
            headers["Connection"] = "keep-alive"

        elif self.family == BrowserFamily.FIREFOX:
            # Firefox header order: User-Agent → Accept → Accept-Language →
            # Accept-Encoding → Connection → Upgrade-Insecure-Requests
            headers["User-Agent"] = self.user_agent
            headers["Accept"] = self.accept
            headers["Accept-Language"] = self.accept_language
            headers["Accept-Encoding"] = self.accept_encoding
            headers["Connection"] = "keep-alive"
            headers["Upgrade-Insecure-Requests"] = "1"

        elif self.family == BrowserFamily.SAFARI:
            # Safari header order: User-Agent → Accept → Accept-Language →
            # Accept-Encoding → Connection
            headers["User-Agent"] = self.user_agent
            headers["Accept"] = self.accept
            headers["Accept-Language"] = self.accept_language
            headers["Accept-Encoding"] = "gzip, deflate, br"
            headers["Connection"] = "keep-alive"

        return headers


# =============================================================================
# Pre-configured browser profiles
# =============================================================================
# These are the profiles that curl_cffi's `impersonate` parameter supports.
# Weights reflect real-world browser market share (Chrome dominant).

CHROME_131_WIN = BrowserProfile(
    name="Chrome 131 Windows",
    family=BrowserFamily.CHROME,
    impersonate="chrome131",
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
    platform="Windows",
    weight=25,
)

CHROME_131_MAC = BrowserProfile(
    name="Chrome 131 macOS",
    family=BrowserFamily.CHROME,
    impersonate="chrome131",
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"macOS"',
    platform="macOS",
    weight=15,
)

CHROME_131_LINUX = BrowserProfile(
    name="Chrome 131 Linux",
    family=BrowserFamily.CHROME,
    impersonate="chrome131",
    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Linux"',
    platform="Linux",
    weight=5,
)

FIREFOX_133_WIN = BrowserProfile(
    name="Firefox 133 Windows",
    family=BrowserFamily.FIREFOX,
    impersonate="firefox133",
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    accept_encoding="gzip, deflate, br, zstd",
    platform="Windows",
    weight=10,
)

FIREFOX_133_MAC = BrowserProfile(
    name="Firefox 133 macOS",
    family=BrowserFamily.FIREFOX,
    impersonate="firefox133",
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    accept_encoding="gzip, deflate, br, zstd",
    platform="macOS",
    weight=5,
)

SAFARI_18_MAC = BrowserProfile(
    name="Safari 18 macOS",
    family=BrowserFamily.SAFARI,
    impersonate="safari18_0",
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    accept_encoding="gzip, deflate, br",
    platform="macOS",
    weight=8,
)

EDGE_131_WIN = BrowserProfile(
    name="Edge 131 Windows",
    family=BrowserFamily.EDGE,
    impersonate="edge131",
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    sec_ch_ua='"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    sec_ch_ua_platform='"Windows"',
    platform="Windows",
    weight=7,
)


# All available profiles
ALL_PROFILES: list[BrowserProfile] = [
    CHROME_131_WIN,
    CHROME_131_MAC,
    CHROME_131_LINUX,
    FIREFOX_133_WIN,
    FIREFOX_133_MAC,
    SAFARI_18_MAC,
    EDGE_131_WIN,
]


class ProfileRotator:
    """Weighted random profile selection with session consistency.

    Selects browser profiles weighted by real-world market share.
    Once a profile is selected for a session (identified by domain),
    it remains consistent for that session to avoid fingerprint
    inconsistencies (e.g., starting as Chrome then switching to
    Firefox mid-session).

    Attributes:
        profiles: Available browser profiles.
        _session_profiles: Map of session_key → locked profile.
    """

    def __init__(self, profiles: list[BrowserProfile] | None = None) -> None:
        self.profiles = profiles or ALL_PROFILES
        self._session_profiles: dict[str, BrowserProfile] = {}

    def select(self, session_key: str | None = None) -> BrowserProfile:
        """Select a browser profile.

        Args:
            session_key: Optional key (e.g. domain) to lock a profile for
                         the duration of a session. If None, a fresh random
                         profile is returned each time.

        Returns:
            A BrowserProfile instance.
        """
        if session_key and session_key in self._session_profiles:
            return self._session_profiles[session_key]

        weights = [p.weight for p in self.profiles]
        profile = random.choices(self.profiles, weights=weights, k=1)[0]

        if session_key:
            self._session_profiles[session_key] = profile

        return profile

    def release_session(self, session_key: str) -> None:
        """Release a session's locked profile (e.g. on rotation)."""
        self._session_profiles.pop(session_key, None)

    def clear_all_sessions(self) -> None:
        """Clear all session locks."""
        self._session_profiles.clear()
