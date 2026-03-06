"""
Tests for proxy orchestration.
"""

import time

import pytest

from arachne_stealth.proxy_manager import (
    Proxy,
    ProxyManager,
    ProxyStatus,
    ProxyTier,
)


class TestProxy:
    """Tests for individual proxy health tracking."""

    def test_new_proxy_is_healthy(self):
        """A new proxy should be healthy."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        assert proxy.status == ProxyStatus.HEALTHY
        assert proxy.success_rate == 1.0
        assert proxy.health_score > 0

    def test_success_rate_calculation(self):
        """success_rate should reflect actual request outcomes."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        proxy.record_success(latency_ms=100)
        proxy.record_success(latency_ms=200)
        proxy.record_failure()

        assert proxy.total_requests == 3
        assert proxy.successful_requests == 2
        assert abs(proxy.success_rate - 2 / 3) < 0.01

    def test_challenge_rate_tracking(self):
        """challenge_rate should track blocked requests."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        proxy.record_success(latency_ms=100)
        proxy.record_failure(is_block=True)

        assert proxy.challenge_rate == 0.5

    def test_avg_latency(self):
        """avg_latency should be calculated from successful requests only."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        proxy.record_success(latency_ms=100)
        proxy.record_success(latency_ms=300)

        assert proxy.avg_latency_ms == 200.0

    def test_auto_quarantine_on_failures(self):
        """5 consecutive failures should auto-quarantine."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        for _ in range(5):
            proxy.record_failure()

        assert proxy.is_quarantined is True
        assert proxy.status == ProxyStatus.QUARANTINED

    def test_degraded_status(self):
        """Low success rate should mark proxy as degraded."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        proxy.record_failure()
        proxy.record_failure()
        proxy.record_failure()
        proxy.record_success(latency_ms=100)

        # 25% success rate should be degraded
        assert proxy.status == ProxyStatus.DEGRADED

    def test_health_score_range(self):
        """health_score should be between 0.0 and 1.0."""
        proxy = Proxy(url="http://test:8000", tier=ProxyTier.DATACENTER)
        proxy.record_success(latency_ms=100)
        assert 0.0 <= proxy.health_score <= 1.0

        proxy2 = Proxy(url="http://test:8001", tier=ProxyTier.DATACENTER)
        for _ in range(5):
            proxy2.record_failure(is_block=True)
        assert proxy2.health_score < proxy.health_score


class TestProxyManager:
    """Tests for proxy pool management."""

    def _make_manager(self) -> ProxyManager:
        """Create a manager with test proxies."""
        mgr = ProxyManager()
        mgr.add_proxy("http://dc1:8000", ProxyTier.DATACENTER)
        mgr.add_proxy("http://dc2:8000", ProxyTier.DATACENTER)
        mgr.add_proxy("http://res1:8000", ProxyTier.RESIDENTIAL)
        return mgr

    def test_select_from_requested_tier(self):
        """select() should return a proxy from the requested tier."""
        mgr = self._make_manager()
        proxy = mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=False)

        assert proxy is not None
        assert proxy.tier == ProxyTier.DATACENTER

    def test_select_escalates_when_empty(self):
        """If requested tier is empty, should try higher tiers."""
        mgr = ProxyManager()
        mgr.add_proxy("http://res1:8000", ProxyTier.RESIDENTIAL)

        # Request datacenter (empty), should fall through to residential
        proxy = mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=False)
        assert proxy is not None
        assert proxy.tier == ProxyTier.RESIDENTIAL

    def test_returns_none_when_all_empty(self):
        """Should return None when no proxies available at any tier."""
        mgr = ProxyManager()
        proxy = mgr.select("test.com", tier=ProxyTier.DATACENTER)
        assert proxy is None

    def test_sticky_assignment(self):
        """Same domain should get the same proxy (sticky mode)."""
        mgr = self._make_manager()
        first = mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=True)
        second = mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=True)

        assert first is second

    def test_different_domains_can_get_different_proxies(self):
        """Different domains should be independently assigned."""
        mgr = self._make_manager()
        p1 = mgr.select("domain1.com", tier=ProxyTier.DATACENTER, sticky=True)
        p2 = mgr.select("domain2.com", tier=ProxyTier.DATACENTER, sticky=True)

        # Both should be valid proxies (may or may not be the same)
        assert p1 is not None
        assert p2 is not None

    def test_quarantined_proxy_skipped(self):
        """Quarantined proxies should not be selected."""
        mgr = ProxyManager()
        mgr.add_proxy("http://bad:8000", ProxyTier.DATACENTER)
        mgr.add_proxy("http://good:8000", ProxyTier.DATACENTER)

        # Quarantine the first one
        bad_proxy = mgr._pools[ProxyTier.DATACENTER][0]
        for _ in range(5):
            bad_proxy.record_failure()

        # Should select the good one
        selected = mgr.select("test.com", sticky=False)
        assert selected is not None
        assert selected.url == "http://good:8000"

    def test_release_domain_removes_lock(self):
        """release_domain should remove the sticky assignment."""
        mgr = self._make_manager()
        mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=True)
        mgr.release_domain("test.com")
        # After release, next select gets a new assignment
        proxy = mgr.select("test.com", tier=ProxyTier.DATACENTER, sticky=True)
        assert proxy is not None

    def test_pool_stats(self):
        """get_pool_stats should return structured data."""
        mgr = self._make_manager()
        stats = mgr.get_pool_stats()

        assert "DATACENTER" in stats
        assert stats["DATACENTER"]["total"] == 2
        assert stats["DATACENTER"]["healthy"] == 2
        assert stats["RESIDENTIAL"]["total"] == 1
