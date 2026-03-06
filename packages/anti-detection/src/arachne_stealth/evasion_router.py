"""
Adaptive Evasion Router — the core anti-detection intelligence.

Automatically escalates from fast/cheap HTTP to slow/expensive stealth
when encountering resistance, AND de-escalates back down once clearance
is obtained. No existing open-source project implements this dual-direction
adaptive system.

Escalation ladder:
    Tier 0: curl_cffi (fast HTTP, JA4 spoofed)
    Tier 1: Pydoll (CDP, Cloudflare specialist)
    Tier 2: Camoufox + behavioral simulation (full stealth)

De-escalation path:
    Browser gets cookies → export to curl_cffi → fast HTTP with cookies
    → on cookie expiry → briefly re-escalate → fresh cookies → repeat

Research ref: Research.md §1.6 — "The Adaptive Evasion Router is R1's core
differentiating concept. No existing open-source project implements this."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from arachne_stealth.cookie_manager import CookieManager

logger = logging.getLogger(__name__)


class EvasionTier(IntEnum):
    """Stealth tiers in the escalation ladder.

    Higher tiers are more evasive but slower and more expensive.
    The router starts at the lowest viable tier and escalates only
    when blocked.
    """
    HTTP_SPOOFED = 0     # curl_cffi with JA4 spoofing (fast, cheap)
    BROWSER_CDP = 1      # Pydoll — direct CDP, Cloudflare specialist
    BROWSER_ENGINE = 2   # Camoufox — C++ engine mods (highest stealth)


@dataclass
class DomainState:
    """Per-domain evasion state.

    Tracks the current escalation tier, anti-bot vendor, cookies,
    escalation history, and circuit breaker state for a single domain.
    """
    domain: str
    current_tier: EvasionTier = EvasionTier.HTTP_SPOOFED
    initial_tier: EvasionTier | None = None  # Set by vendor detection
    vendor: str = "unknown"
    vendor_confidence: float = 0.0

    # Escalation tracking
    escalation_count: int = 0
    deescalation_count: int = 0
    last_escalation_at: float = 0
    last_success_at: float = 0

    # Circuit breaker
    consecutive_failures: int = 0
    circuit_open: bool = False
    circuit_opened_at: float = 0
    max_consecutive_failures: int = 5

    # Request stats
    total_requests: int = 0
    successful_requests: int = 0
    blocked_requests: int = 0

    @property
    def success_rate(self) -> float:
        """Current success rate (0.0 - 1.0)."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    def record_success(self) -> None:
        """Record a successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.last_success_at = time.time()

        # Close circuit breaker on success
        if self.circuit_open:
            self.circuit_open = False
            logger.info(f"Circuit breaker CLOSED for {self.domain}")

    def record_failure(self, is_block: bool = False) -> None:
        """Record a failed request.

        Args:
            is_block: True if the failure was due to anti-bot blocking (403/challenge).
        """
        self.total_requests += 1
        self.consecutive_failures += 1

        if is_block:
            self.blocked_requests += 1

        # Trip circuit breaker
        if self.consecutive_failures >= self.max_consecutive_failures:
            if not self.circuit_open:
                self.circuit_open = True
                self.circuit_opened_at = time.time()
                logger.warning(
                    f"Circuit breaker OPENED for {self.domain} "
                    f"({self.consecutive_failures} consecutive failures)"
                )


@dataclass
class EvasionDecision:
    """Decision output from the Evasion Router.

    Tells the caller which tier to use, what backend, what proxy,
    and any cookies to inject.
    """
    tier: EvasionTier
    backend_name: str  # "curl_cffi", "pydoll", "camoufox"
    proxy_tier: str = "direct"  # "direct", "datacenter", "residential", "mobile"
    cookies: dict[str, str] | None = None
    should_deescalate: bool = False
    reason: str = ""


# Maps vendor to recommended starting tier
VENDOR_TIER_MAP: dict[str, EvasionTier] = {
    "none": EvasionTier.HTTP_SPOOFED,
    "unknown": EvasionTier.HTTP_SPOOFED,
    "cloudflare_basic": EvasionTier.HTTP_SPOOFED,
    "cloudflare_turnstile": EvasionTier.BROWSER_CDP,
    "cloudflare_bot_management": EvasionTier.BROWSER_ENGINE,
    "akamai": EvasionTier.BROWSER_ENGINE,
    "datadome": EvasionTier.BROWSER_ENGINE,
    "kasada": EvasionTier.BROWSER_ENGINE,
    "perimeterx": EvasionTier.BROWSER_ENGINE,
    "aws_waf": EvasionTier.HTTP_SPOOFED,
    "recaptcha": EvasionTier.BROWSER_CDP,
    "hcaptcha": EvasionTier.BROWSER_CDP,
}

# Maps tier to backend name
TIER_BACKEND_MAP: dict[EvasionTier, str] = {
    EvasionTier.HTTP_SPOOFED: "curl_cffi",
    EvasionTier.BROWSER_CDP: "pydoll",
    EvasionTier.BROWSER_ENGINE: "camoufox",
}

# Maps tier to recommended proxy tier
TIER_PROXY_MAP: dict[EvasionTier, str] = {
    EvasionTier.HTTP_SPOOFED: "datacenter",
    EvasionTier.BROWSER_CDP: "residential",
    EvasionTier.BROWSER_ENGINE: "residential",
}


class EvasionRouter:
    """Adaptive multi-tier evasion routing system.

    The core innovation of Arachne's anti-detection engine. Automatically
    selects and adjusts the stealth tier based on:
        - Detected anti-bot vendor (if known)
        - Response feedback (success/block/challenge)
        - Cookie availability (can we de-escalate to HTTP?)
        - Circuit breaker state (is the domain unreachable?)

    Lifecycle:
        1. New domain → vendor detection (optional) → set initial tier
        2. Request at current tier → success → record, maybe de-escalate
        3. Request at current tier → blocked → escalate to next tier
        4. After browser success → export cookies → de-escalate to HTTP
        5. On cookie expiry → briefly re-escalate → refresh → de-escalate

    Usage:
        router = EvasionRouter()
        decision = router.decide("example.com")
        # ... execute request based on decision ...
        router.report_success("example.com", cookies=[...])
        # OR
        router.report_failure("example.com", is_block=True)
    """

    def __init__(self, cookie_manager: CookieManager | None = None) -> None:
        self._states: dict[str, DomainState] = {}
        self._cookies = cookie_manager or CookieManager()

    @property
    def cookie_manager(self) -> CookieManager:
        """Access the cookie manager for direct cookie operations."""
        return self._cookies

    def decide(self, domain: str) -> EvasionDecision:
        """Decide the optimal evasion strategy for a domain.

        This is the main entry point. Call this before each request
        to get the recommended tier, backend, proxy, and cookies.

        Args:
            domain: Target domain (e.g., "example.com").

        Returns:
            EvasionDecision with the recommended strategy.
        """
        state = self._get_or_create_state(domain)

        # Circuit breaker check
        if state.circuit_open:
            # Allow retry after 60 seconds (half-open)
            if time.time() - state.circuit_opened_at > 60:
                logger.info(f"Circuit breaker half-open for {domain}, retrying at highest tier")
                state.current_tier = EvasionTier.BROWSER_ENGINE
            else:
                return EvasionDecision(
                    tier=state.current_tier,
                    backend_name=TIER_BACKEND_MAP[state.current_tier],
                    proxy_tier="residential",
                    reason=f"Circuit breaker open ({state.consecutive_failures} failures)",
                )

        # Check if we can de-escalate to HTTP using cached cookies
        valid_cookies = self._cookies.get_valid_cookies(domain)
        if valid_cookies and state.current_tier > EvasionTier.HTTP_SPOOFED:
            return EvasionDecision(
                tier=EvasionTier.HTTP_SPOOFED,
                backend_name="curl_cffi",
                proxy_tier=TIER_PROXY_MAP[EvasionTier.HTTP_SPOOFED],
                cookies=valid_cookies,
                should_deescalate=True,
                reason=f"De-escalating to HTTP with {len(valid_cookies)} cached cookies",
            )

        # Check if cookies need proactive refresh
        if self._cookies.needs_refresh(domain) and valid_cookies:
            # Cookies expiring soon — proactively escalate to refresh
            return EvasionDecision(
                tier=EvasionTier.BROWSER_CDP,
                backend_name=TIER_BACKEND_MAP[EvasionTier.BROWSER_CDP],
                proxy_tier=TIER_PROXY_MAP[EvasionTier.BROWSER_CDP],
                reason=f"Proactive cookie refresh for {domain}",
            )

        # Default: use current tier
        tier = state.current_tier
        return EvasionDecision(
            tier=tier,
            backend_name=TIER_BACKEND_MAP[tier],
            proxy_tier=TIER_PROXY_MAP[tier],
            reason=f"Standard request at tier {tier.name}",
        )

    def report_success(
        self,
        domain: str,
        cookies: list[Any] | None = None,
        estimated_cookie_ttl: float = 1800.0,
    ) -> None:
        """Report a successful request for a domain.

        If cookies were obtained (e.g., from a browser session), they're
        stored for future HTTP de-escalation.

        Args:
            domain: Target domain.
            cookies: Optional browser cookies to store.
            estimated_cookie_ttl: Estimated cookie validity in seconds.
        """
        state = self._get_or_create_state(domain)
        state.record_success()

        if cookies:
            from arachne_stealth.browser_backend import Cookie

            cookie_objects = []
            for c in cookies:
                if isinstance(c, Cookie):
                    cookie_objects.append(c)
                elif isinstance(c, dict):
                    cookie_objects.append(Cookie(
                        name=c.get("name", ""),
                        value=c.get("value", ""),
                        domain=c.get("domain", domain),
                        path=c.get("path", "/"),
                        expires=c.get("expires", -1),
                        http_only=c.get("http_only", c.get("httpOnly", False)),
                        secure=c.get("secure", False),
                        same_site=c.get("same_site", c.get("sameSite", "Lax")),
                    ))

            self._cookies.store(
                domain=domain,
                cookies=cookie_objects,
                source=TIER_BACKEND_MAP[state.current_tier],
                estimated_ttl=estimated_cookie_ttl,
            )

            state.deescalation_count += 1
            logger.info(
                f"Evasion success for {domain} at tier {state.current_tier.name}, "
                f"stored {len(cookie_objects)} cookies for de-escalation"
            )

    def report_failure(
        self,
        domain: str,
        is_block: bool = True,
        status_code: int | None = None,
    ) -> EvasionTier:
        """Report a failed request and escalate if needed.

        Args:
            domain: Target domain.
            is_block: True if the failure was anti-bot blocking.
            status_code: HTTP status code (for logging).

        Returns:
            The new tier after escalation (or same if already at max).
        """
        state = self._get_or_create_state(domain)
        state.record_failure(is_block=is_block)

        if is_block and not state.circuit_open:
            old_tier = state.current_tier
            new_tier = self._escalate(state)

            if new_tier != old_tier:
                # Invalidate cookies on escalation — they clearly didn't work
                self._cookies.invalidate(domain)

                logger.info(
                    f"Evasion ESCALATED for {domain}: "
                    f"{old_tier.name} → {new_tier.name} "
                    f"(status={status_code}, consecutive_failures={state.consecutive_failures})"
                )
            else:
                logger.warning(
                    f"Already at max tier for {domain} ({new_tier.name}), "
                    f"consecutive_failures={state.consecutive_failures}"
                )

        return state.current_tier

    def set_vendor(
        self,
        domain: str,
        vendor: str,
        confidence: float = 1.0,
    ) -> None:
        """Set the detected anti-bot vendor for a domain.

        This is called by the vendor detection system (Step 8) to
        pre-configure the starting tier based on known protection.

        Args:
            domain: Target domain.
            vendor: Vendor name (e.g., "cloudflare_turnstile").
            confidence: Detection confidence (0.0-1.0).
        """
        state = self._get_or_create_state(domain)
        state.vendor = vendor
        state.vendor_confidence = confidence

        # Set initial tier based on vendor
        initial_tier = VENDOR_TIER_MAP.get(vendor, EvasionTier.HTTP_SPOOFED)
        state.initial_tier = initial_tier
        state.current_tier = initial_tier

        logger.info(
            f"Vendor detected for {domain}: {vendor} "
            f"(confidence={confidence:.2f}, initial_tier={initial_tier.name})"
        )

    def get_state(self, domain: str) -> DomainState | None:
        """Get the current state for a domain."""
        return self._states.get(domain)

    def stats(self) -> dict[str, Any]:
        """Get router statistics for all domains."""
        return {
            "total_domains": len(self._states),
            "domains": {
                domain: {
                    "tier": state.current_tier.name,
                    "vendor": state.vendor,
                    "success_rate": round(state.success_rate, 3),
                    "total_requests": state.total_requests,
                    "escalations": state.escalation_count,
                    "deescalations": state.deescalation_count,
                    "circuit_open": state.circuit_open,
                }
                for domain, state in self._states.items()
            },
            "cookie_stats": self._cookies.stats(),
        }

    def _get_or_create_state(self, domain: str) -> DomainState:
        """Get or create domain state."""
        if domain not in self._states:
            self._states[domain] = DomainState(domain=domain)
        return self._states[domain]

    def _escalate(self, state: DomainState) -> EvasionTier:
        """Escalate to the next tier in the ladder.

        Returns the new tier (may be same if already at max).
        """
        max_tier = max(EvasionTier)
        if state.current_tier < max_tier:
            state.current_tier = EvasionTier(state.current_tier + 1)
            state.escalation_count += 1
            state.last_escalation_at = time.time()
        return state.current_tier
