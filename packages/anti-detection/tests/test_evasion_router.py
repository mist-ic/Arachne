"""
Tests for the Adaptive Evasion Router — the core innovation.
"""

import time

import pytest

from arachne_stealth.browser_backend import Cookie
from arachne_stealth.cookie_manager import CookieManager
from arachne_stealth.evasion_router import (
    DomainState,
    EvasionDecision,
    EvasionRouter,
    EvasionTier,
    TIER_BACKEND_MAP,
    VENDOR_TIER_MAP,
)


class TestEvasionTier:
    """Tests for the tier enum."""

    def test_tier_ordering(self):
        """Tiers should be ordered: HTTP < CDP < ENGINE."""
        assert EvasionTier.HTTP_SPOOFED < EvasionTier.BROWSER_CDP
        assert EvasionTier.BROWSER_CDP < EvasionTier.BROWSER_ENGINE

    def test_tier_values(self):
        """Tier values should match the escalation ladder."""
        assert EvasionTier.HTTP_SPOOFED == 0
        assert EvasionTier.BROWSER_CDP == 1
        assert EvasionTier.BROWSER_ENGINE == 2

    def test_all_tiers_have_backends(self):
        """Every tier must have a mapped backend name."""
        for tier in EvasionTier:
            assert tier in TIER_BACKEND_MAP


class TestEvasionRouter:
    """Tests for the adaptive evasion routing system."""

    def test_new_domain_starts_at_tier_0(self):
        """Unknown domains should start at the cheapest tier (HTTP)."""
        router = EvasionRouter()
        decision = router.decide("example.com")
        assert decision.tier == EvasionTier.HTTP_SPOOFED
        assert decision.backend_name == "curl_cffi"

    def test_escalation_on_failure(self):
        """After a blocked request, the tier should escalate."""
        router = EvasionRouter()
        router.decide("example.com")

        # Report a block
        new_tier = router.report_failure("example.com", is_block=True)
        assert new_tier == EvasionTier.BROWSER_CDP

        # Next decision should use the escalated tier
        decision = router.decide("example.com")
        assert decision.tier == EvasionTier.BROWSER_CDP
        assert decision.backend_name == "pydoll"

    def test_double_escalation(self):
        """Two consecutive blocks should escalate to max tier."""
        router = EvasionRouter()
        router.decide("example.com")

        router.report_failure("example.com", is_block=True)
        router.report_failure("example.com", is_block=True)

        decision = router.decide("example.com")
        assert decision.tier == EvasionTier.BROWSER_ENGINE
        assert decision.backend_name == "camoufox"

    def test_max_tier_cannot_escalate_further(self):
        """At max tier, further failures should not crash."""
        router = EvasionRouter()
        router.report_failure("example.com", is_block=True)
        router.report_failure("example.com", is_block=True)
        # Already at max — should stay there
        tier = router.report_failure("example.com", is_block=True)
        assert tier == EvasionTier.BROWSER_ENGINE

    def test_deescalation_with_cookies(self):
        """After browser success with cookies, should de-escalate to HTTP."""
        router = EvasionRouter()

        # Escalate to browser
        router.report_failure("example.com", is_block=True)
        assert router.decide("example.com").tier == EvasionTier.BROWSER_CDP

        # Browser succeeds and returns cookies
        cookies = [
            Cookie(name="cf_clearance", value="abc123", domain="example.com"),
            Cookie(name="session", value="xyz789", domain="example.com"),
        ]
        router.report_success("example.com", cookies=cookies)

        # Next decision should de-escalate to HTTP with cookies
        decision = router.decide("example.com")
        assert decision.tier == EvasionTier.HTTP_SPOOFED
        assert decision.should_deescalate is True
        assert decision.cookies is not None
        assert "cf_clearance" in decision.cookies
        assert decision.cookies["cf_clearance"] == "abc123"

    def test_deescalation_with_dict_cookies(self):
        """Should accept cookies as dicts (from Temporal serialization)."""
        router = EvasionRouter()
        router.report_failure("example.com", is_block=True)

        dict_cookies = [
            {"name": "token", "value": "secret123", "domain": "example.com"},
        ]
        router.report_success("example.com", cookies=dict_cookies)

        decision = router.decide("example.com")
        assert decision.cookies is not None
        assert decision.cookies["token"] == "secret123"

    def test_vendor_sets_initial_tier(self):
        """Setting a vendor should pre-configure the starting tier."""
        router = EvasionRouter()
        router.set_vendor("cloudflare-site.com", "cloudflare_turnstile", confidence=0.95)

        decision = router.decide("cloudflare-site.com")
        assert decision.tier == EvasionTier.BROWSER_CDP
        assert decision.backend_name == "pydoll"

    def test_vendor_akamai_starts_at_engine(self):
        """Akamai should start at the highest browser tier."""
        router = EvasionRouter()
        router.set_vendor("akamai-site.com", "akamai")

        decision = router.decide("akamai-site.com")
        assert decision.tier == EvasionTier.BROWSER_ENGINE

    def test_circuit_breaker_opens(self):
        """5+ consecutive failures should trip the circuit breaker."""
        router = EvasionRouter()

        for _ in range(6):
            router.report_failure("broken.com", is_block=True)

        state = router.get_state("broken.com")
        assert state is not None
        assert state.circuit_open is True

    def test_success_closes_circuit_breaker(self):
        """A success should close the circuit breaker."""
        router = EvasionRouter()

        # Trip circuit breaker
        for _ in range(6):
            router.report_failure("broken.com", is_block=True)

        state = router.get_state("broken.com")
        assert state.circuit_open is True

        # Success should close it
        router.report_success("broken.com")
        assert state.circuit_open is False
        assert state.consecutive_failures == 0

    def test_independent_domain_states(self):
        """Different domains should have independent state."""
        router = EvasionRouter()

        router.report_failure("blocked.com", is_block=True)
        router.report_success("easy.com")

        blocked_decision = router.decide("blocked.com")
        easy_decision = router.decide("easy.com")

        assert blocked_decision.tier == EvasionTier.BROWSER_CDP
        assert easy_decision.tier == EvasionTier.HTTP_SPOOFED

    def test_success_rate_tracking(self):
        """DomainState should track success rate accurately."""
        router = EvasionRouter()

        router.report_success("test.com")
        router.report_success("test.com")
        router.report_failure("test.com", is_block=False)

        state = router.get_state("test.com")
        assert state.total_requests == 3
        assert state.successful_requests == 2
        assert abs(state.success_rate - 2 / 3) < 0.01

    def test_stats_output(self):
        """stats() should return a structured summary."""
        router = EvasionRouter()
        router.decide("example.com")
        router.report_success("example.com")

        stats = router.stats()
        assert "total_domains" in stats
        assert stats["total_domains"] == 1
        assert "example.com" in stats["domains"]
        assert "cookie_stats" in stats


class TestCookieManager:
    """Tests for per-domain cookie management."""

    def _make_cookies(self, *names: str) -> list[Cookie]:
        return [Cookie(name=n, value=f"val_{n}", domain="test.com") for n in names]

    def test_store_and_get(self):
        """Should store and retrieve cookies by domain."""
        cm = CookieManager()
        cookies = self._make_cookies("a", "b")
        cm.store("test.com", cookies)

        jar = cm.get("test.com")
        assert jar is not None
        assert len(jar.cookies) == 2
        assert jar.domain == "test.com"

    def test_get_valid_cookies_returns_dict(self):
        """get_valid_cookies should return name→value dict."""
        cm = CookieManager()
        cm.store("test.com", self._make_cookies("token", "session"))

        result = cm.get_valid_cookies("test.com")
        assert result is not None
        assert result["token"] == "val_token"
        assert result["session"] == "val_session"

    def test_unknown_domain_returns_none(self):
        """Unknown domain should return None."""
        cm = CookieManager()
        assert cm.get("unknown.com") is None
        assert cm.get_valid_cookies("unknown.com") is None

    def test_expired_cookies_return_none(self):
        """Expired cookies should return None from get_valid_cookies."""
        cm = CookieManager()
        cm.store("test.com", self._make_cookies("a"), estimated_ttl=0.01)

        # Wait for expiry
        time.sleep(0.02)

        result = cm.get_valid_cookies("test.com")
        assert result is None

    def test_needs_refresh_for_unknown(self):
        """Unknown domain should always need refresh."""
        cm = CookieManager()
        assert cm.needs_refresh("unknown.com") is True

    def test_invalidate_removes_cookies(self):
        """invalidate() should remove cookies for a domain."""
        cm = CookieManager()
        cm.store("test.com", self._make_cookies("a"))
        cm.invalidate("test.com")
        assert cm.get("test.com") is None

    def test_refresh_increments_count(self):
        """Storing cookies for same domain should increment refresh_count."""
        cm = CookieManager()
        cm.store("test.com", self._make_cookies("a"))
        cm.store("test.com", self._make_cookies("b"))

        jar = cm.get("test.com")
        assert jar is not None
        assert jar.refresh_count == 1

    def test_stats_output(self):
        """stats() should return structured data."""
        cm = CookieManager()
        cm.store("a.com", self._make_cookies("x"))
        cm.store("b.com", self._make_cookies("y", "z"))

        stats = cm.stats()
        assert stats["total_domains"] == 2
        assert "a.com" in stats["domains"]
        assert stats["domains"]["b.com"]["cookie_count"] == 2
