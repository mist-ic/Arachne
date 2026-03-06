"""
Fingerprint Observatory — diagnostic tool for fingerprint analysis.

Captures Arachne's own outgoing fingerprints and compares them against
real browser baselines. This answers the question: "How closely does
our curl_cffi/browser session match a real browser?"

Features:
    - Capture JA4/JA4H fingerprint hashes from curl_cffi sessions
    - HTTP/2 SETTINGS frame analysis
    - Header ordering analysis
    - Baseline profiles from real browser data
    - Deviation reports highlighting mismatches

Usage:
    observatory = FingerprintObservatory()
    snapshot = await observatory.capture("https://tls.browserleaks.com/json")
    report = observatory.compare(snapshot, baseline="chrome131")
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FingerprintSnapshot:
    """A point-in-time capture of outgoing request fingerprints.

    Captures the key signals that anti-bot systems inspect to
    distinguish real browsers from automated tools.
    """
    # Identifiers
    profile_used: str = ""
    target_url: str = ""
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # TLS fingerprint (JA4 format)
    ja4_hash: str = ""        # e.g., "t13d1517h2_8daaf6152771_b0da82dd1658"
    ja4h_hash: str = ""       # HTTP fingerprint hash

    # Header analysis
    header_order: list[str] = field(default_factory=list)
    headers_sent: dict[str, str] = field(default_factory=dict)

    # HTTP/2 analysis
    h2_settings: dict[str, int] = field(default_factory=dict)
    h2_window_size: int = 0
    h2_priority_frames: list[dict[str, Any]] = field(default_factory=list)

    # Raw TLS info (if available)
    tls_version: str = ""
    cipher_suite: str = ""
    supported_extensions: list[str] = field(default_factory=list)

    def fingerprint_hash(self) -> str:
        """Generate a composite fingerprint hash for comparison."""
        components = [
            self.ja4_hash,
            ",".join(self.header_order),
            json.dumps(self.h2_settings, sort_keys=True),
        ]
        combined = "|".join(components)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


@dataclass
class FingerprintBaseline:
    """Known-good fingerprint from a real browser.

    Used as a reference point for comparison. If our snapshot
    matches the baseline, we're indistinguishable from a real browser.
    """
    browser: str
    ja4_hash: str
    header_order: list[str]
    h2_settings: dict[str, int]
    h2_window_size: int


@dataclass
class DeviationReport:
    """Report comparing a snapshot against a baseline.

    Lists all mismatches between our fingerprint and the target
    browser's real fingerprint.
    """
    snapshot_profile: str
    baseline_browser: str
    overall_match: float  # 0.0-1.0 (1.0 = perfect match)
    deviations: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Known baselines from real browsers (from ja4db.com and tls.peet.ws)
# =============================================================================

BASELINES: dict[str, FingerprintBaseline] = {
    "chrome131": FingerprintBaseline(
        browser="Chrome 131",
        ja4_hash="t13d1517h2_8daaf6152771_b0da82dd1658",
        header_order=[
            "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
            "Upgrade-Insecure-Requests", "User-Agent", "Accept",
            "Accept-Encoding", "Accept-Language", "Connection",
        ],
        h2_settings={
            "HEADER_TABLE_SIZE": 65536,
            "ENABLE_PUSH": 0,
            "INITIAL_WINDOW_SIZE": 6291456,
            "MAX_HEADER_LIST_SIZE": 262144,
        },
        h2_window_size=15728640,
    ),
    "firefox133": FingerprintBaseline(
        browser="Firefox 133",
        ja4_hash="t13d1516h2_8daaf6152771_e5627efa2ab1",
        header_order=[
            "User-Agent", "Accept", "Accept-Language",
            "Accept-Encoding", "Connection", "Upgrade-Insecure-Requests",
        ],
        h2_settings={
            "HEADER_TABLE_SIZE": 65536,
            "INITIAL_WINDOW_SIZE": 131072,
            "MAX_FRAME_SIZE": 16384,
        },
        h2_window_size=12517377,
    ),
    "safari18": FingerprintBaseline(
        browser="Safari 18",
        ja4_hash="t13d1517h2_8daaf6152771_3ed4f4a1c2e7",
        header_order=[
            "User-Agent", "Accept", "Accept-Language",
            "Accept-Encoding", "Connection",
        ],
        h2_settings={
            "HEADER_TABLE_SIZE": 4096,
            "ENABLE_PUSH": 0,
            "INITIAL_WINDOW_SIZE": 2097152,
            "MAX_CONCURRENT_STREAMS": 100,
        },
        h2_window_size=10485760,
    ),
}


class FingerprintObservatory:
    """Diagnostic tool for analyzing outgoing fingerprints.

    Captures fingerprints from our requests and compares them against
    real browser baselines. Used to verify that curl_cffi profiles
    are producing accurate fingerprints.
    """

    def __init__(self) -> None:
        self._snapshots: list[FingerprintSnapshot] = []
        self._baselines = dict(BASELINES)

    async def capture(
        self,
        target_url: str = "https://tls.browserleaks.com/json",
        profile_name: str = "",
    ) -> FingerprintSnapshot:
        """Capture a fingerprint snapshot by making a request.

        Makes a request to a fingerprint analysis service and
        parses the response to extract our TLS/HTTP fingerprint.

        Args:
            target_url: URL of a fingerprint analysis service.
            profile_name: Name of the browser profile used.

        Returns:
            FingerprintSnapshot with captured fingerprint data.
        """
        from arachne_stealth.http_client import StealthHttpClient

        client = StealthHttpClient()
        try:
            result = await client.fetch(target_url, session_key=f"_fingerprint_{profile_name}")

            # Try to parse fingerprint from response
            snapshot = FingerprintSnapshot(
                profile_used=profile_name or result.profile_used,
                target_url=target_url,
                headers_sent=result.headers,
            )

            # Try to extract JA4 from response body (if using tls-check service)
            try:
                data = json.loads(result.html)
                snapshot.ja4_hash = data.get("ja4", data.get("ja4_hash", ""))
                snapshot.tls_version = data.get("tls_version", "")
                snapshot.cipher_suite = data.get("cipher_suite", "")
            except (json.JSONDecodeError, KeyError):
                pass

            self._snapshots.append(snapshot)
            return snapshot

        finally:
            await client.close_all()

    def compare(
        self,
        snapshot: FingerprintSnapshot,
        baseline_name: str = "chrome131",
    ) -> DeviationReport:
        """Compare a snapshot against a browser baseline.

        Checks each fingerprint component for match/mismatch and
        calculates an overall match score.

        Args:
            snapshot: Captured fingerprint snapshot.
            baseline_name: Name of baseline to compare against.

        Returns:
            DeviationReport with match score and deviations.
        """
        baseline = self._baselines.get(baseline_name)
        if not baseline:
            return DeviationReport(
                snapshot_profile=snapshot.profile_used,
                baseline_browser=baseline_name,
                overall_match=0.0,
                deviations=[{"component": "baseline", "detail": f"Unknown baseline: {baseline_name}"}],
            )

        deviations = []
        checks = 0
        matches = 0

        # Check JA4 hash
        checks += 1
        if snapshot.ja4_hash and snapshot.ja4_hash == baseline.ja4_hash:
            matches += 1
        elif snapshot.ja4_hash:
            deviations.append({
                "component": "JA4",
                "expected": baseline.ja4_hash,
                "actual": snapshot.ja4_hash,
                "severity": "HIGH",
            })

        # Check header ordering
        checks += 1
        if snapshot.header_order == baseline.header_order:
            matches += 1
        elif snapshot.header_order:
            deviations.append({
                "component": "Header Order",
                "expected": baseline.header_order,
                "actual": snapshot.header_order,
                "severity": "MEDIUM",
            })

        # Check H2 settings
        checks += 1
        if snapshot.h2_settings == baseline.h2_settings:
            matches += 1
        elif snapshot.h2_settings:
            deviations.append({
                "component": "HTTP/2 SETTINGS",
                "expected": baseline.h2_settings,
                "actual": snapshot.h2_settings,
                "severity": "HIGH",
            })

        overall_match = matches / checks if checks > 0 else 0.0

        return DeviationReport(
            snapshot_profile=snapshot.profile_used,
            baseline_browser=baseline.browser,
            overall_match=round(overall_match, 3),
            deviations=deviations,
        )

    @property
    def history(self) -> list[FingerprintSnapshot]:
        """Get all captured snapshots."""
        return list(self._snapshots)
