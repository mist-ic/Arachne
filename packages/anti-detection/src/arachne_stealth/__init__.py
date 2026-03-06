"""
arachne_stealth — Anti-detection engine for Arachne.

Provides TLS fingerprint spoofing, stealth browser backends,
adaptive evasion routing, proxy orchestration, human behavior
simulation, vendor detection, and API discovery.

Quick start:
    from arachne_stealth import StealthHttpClient, EvasionRouter

    client = StealthHttpClient()
    result = await client.fetch("https://example.com")

    router = EvasionRouter()
    decision = router.decide("example.com")
"""

from arachne_stealth.http_client import FetchResult, StealthHttpClient
from arachne_stealth.profiles import (
    ALL_PROFILES,
    BrowserFamily,
    BrowserProfile,
    ProfileRotator,
)
from arachne_stealth.browser_backend import BrowserBackend, Cookie, PageResult
from arachne_stealth.cookie_manager import CookieJar, CookieManager
from arachne_stealth.evasion_router import (
    DomainState,
    EvasionDecision,
    EvasionRouter,
    EvasionTier,
)
from arachne_stealth.behavior import BehaviorProfile, BehaviorSimulator
from arachne_stealth.proxy_manager import Proxy, ProxyManager, ProxyTier
from arachne_stealth.fingerprint import (
    DeviationReport,
    FingerprintObservatory,
    FingerprintSnapshot,
)
from arachne_stealth.vendor_detect import VendorDetection, detect_vendor, probe_domain
from arachne_stealth.api_discovery import (
    APIDiscoveryReport,
    DiscoveredAPI,
    analyze_network_requests,
    reproduce_api,
)

__all__ = [
    # HTTP client
    "FetchResult",
    "StealthHttpClient",
    # Profiles
    "ALL_PROFILES",
    "BrowserFamily",
    "BrowserProfile",
    "ProfileRotator",
    # Browser backends
    "BrowserBackend",
    "Cookie",
    "PageResult",
    # Cookie management
    "CookieJar",
    "CookieManager",
    # Evasion Router
    "DomainState",
    "EvasionDecision",
    "EvasionRouter",
    "EvasionTier",
    # Behavior simulation
    "BehaviorProfile",
    "BehaviorSimulator",
    # Proxy
    "Proxy",
    "ProxyManager",
    "ProxyTier",
    # Fingerprint
    "DeviationReport",
    "FingerprintObservatory",
    "FingerprintSnapshot",
    # Vendor detection
    "VendorDetection",
    "detect_vendor",
    "probe_domain",
    # API discovery
    "APIDiscoveryReport",
    "DiscoveredAPI",
    "analyze_network_requests",
    "reproduce_api",
]
