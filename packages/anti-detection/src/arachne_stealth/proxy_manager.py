"""
Proxy orchestration — intelligent routing through proxy pools.

Manages per-domain proxy pools with health scoring, tier escalation
(direct → datacenter → residential → mobile), rate limiting, and
circuit breaker patterns.

The proxy tier is recommended by the Evasion Router based on the
site's protection level. Residential and mobile proxies have higher
trust scores but cost more — the system only escalates when needed.

Research ref: Research.md §1.7 — Proxy orchestration strategy
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ProxyTier(IntEnum):
    """Proxy quality tiers, ordered by trust level."""
    DIRECT = 0          # No proxy (fastest, most likely to be blocked)
    DATACENTER = 1      # Datacenter IPs (cheap, moderate trust)
    RESIDENTIAL = 2     # Residential IPs (expensive, high trust)
    MOBILE = 3          # Mobile IPs (most expensive, highest trust)


class ProxyStatus(StrEnum):
    """Health status of a proxy."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


@dataclass
class Proxy:
    """A single proxy endpoint with health tracking."""
    url: str                          # http://user:pass@host:port
    tier: ProxyTier
    provider: str = "manual"          # Provider name for attribution

    # Health metrics
    total_requests: int = 0
    successful_requests: int = 0
    blocked_requests: int = 0         # 403/challenge responses
    total_latency_ms: int = 0         # Sum of all request latencies
    consecutive_failures: int = 0

    # Quarantine
    quarantined_at: float = 0
    quarantine_duration: float = 300.0  # 5 minutes default

    # Per-domain tracking
    domain_usage: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def challenge_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.blocked_requests / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    @property
    def status(self) -> ProxyStatus:
        if self.is_quarantined:
            return ProxyStatus.QUARANTINED
        if self.success_rate < 0.5 or self.consecutive_failures >= 3:
            return ProxyStatus.DEGRADED
        return ProxyStatus.HEALTHY

    @property
    def is_quarantined(self) -> bool:
        if self.quarantined_at == 0:
            return False
        return (time.time() - self.quarantined_at) < self.quarantine_duration

    @property
    def health_score(self) -> float:
        """Composite health score (0.0-1.0, higher is better).

        Weighted combination:
            - 40% success rate
            - 30% inverse challenge rate
            - 30% latency score (normalized to 0-1)
        """
        latency_score = max(0, 1.0 - (self.avg_latency_ms / 10000))
        return (
            0.4 * self.success_rate
            + 0.3 * (1.0 - self.challenge_rate)
            + 0.3 * latency_score
        )

    def record_success(self, latency_ms: int, domain: str = "") -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency_ms += latency_ms
        self.consecutive_failures = 0
        if domain:
            self.domain_usage[domain] = self.domain_usage.get(domain, 0) + 1

    def record_failure(self, is_block: bool = False, domain: str = "") -> None:
        self.total_requests += 1
        self.consecutive_failures += 1
        if is_block:
            self.blocked_requests += 1
        if domain:
            self.domain_usage[domain] = self.domain_usage.get(domain, 0) + 1
        # Auto-quarantine on persistent failures
        if self.consecutive_failures >= 5:
            self.quarantined_at = time.time()
            logger.warning(f"Proxy quarantined: {self.url[:30]}...")


class ProxyManager:
    """Intelligent proxy pool management with health scoring.

    Manages proxy pools organized by tier, with per-domain assignment,
    health-based selection, automatic quarantine, and tier escalation.

    The Evasion Router tells the ProxyManager which tier to use, and
    the ProxyManager selects the healthiest proxy from that tier's pool.

    Usage:
        manager = ProxyManager()
        manager.add_proxy("http://user:pass@dc.proxy.com:8000", ProxyTier.DATACENTER)
        manager.add_proxy("http://user:pass@res.proxy.com:8000", ProxyTier.RESIDENTIAL)

        proxy = manager.select("example.com", ProxyTier.DATACENTER)
        # ... use proxy.url in request ...
        manager.record_success(proxy, latency_ms=350, domain="example.com")
    """

    def __init__(self) -> None:
        self._pools: dict[ProxyTier, list[Proxy]] = {tier: [] for tier in ProxyTier}
        self._domain_locks: dict[str, Proxy] = {}  # Per-domain sticky proxy

    def add_proxy(
        self,
        url: str,
        tier: ProxyTier,
        provider: str = "manual",
    ) -> None:
        """Add a proxy to the pool."""
        proxy = Proxy(url=url, tier=tier, provider=provider)
        self._pools[tier].append(proxy)
        logger.info(f"Added {tier.name} proxy from {provider}")

    def select(
        self,
        domain: str,
        tier: ProxyTier = ProxyTier.DATACENTER,
        sticky: bool = True,
    ) -> Proxy | None:
        """Select the best proxy for a domain from the requested tier.

        Selection strategy:
            1. If sticky and domain already has a locked proxy → return it
            2. Filter out quarantined proxies
            3. Sort by health score (descending)
            4. If no proxies at requested tier → try higher tiers

        Args:
            domain: Target domain.
            tier: Requested proxy tier.
            sticky: If True, lock proxy to domain for session consistency.

        Returns:
            Selected Proxy, or None if no proxies available.
        """
        # Check for sticky domain lock
        if sticky and domain in self._domain_locks:
            locked = self._domain_locks[domain]
            if not locked.is_quarantined:
                return locked
            else:
                del self._domain_locks[domain]

        # Try requested tier, then escalate
        for try_tier in range(tier, max(ProxyTier) + 1):
            candidates = [
                p for p in self._pools[ProxyTier(try_tier)]
                if not p.is_quarantined
            ]

            if candidates:
                # Sort by health score, pick from top 3 (with randomness)
                candidates.sort(key=lambda p: p.health_score, reverse=True)
                top_n = min(3, len(candidates))
                selected = random.choice(candidates[:top_n])

                if sticky:
                    self._domain_locks[domain] = selected

                return selected

        # No proxies at any tier — return None (direct connection)
        return None

    def record_success(
        self,
        proxy: Proxy,
        latency_ms: int,
        domain: str = "",
    ) -> None:
        """Record a successful request through a proxy."""
        proxy.record_success(latency_ms=latency_ms, domain=domain)

    def record_failure(
        self,
        proxy: Proxy,
        is_block: bool = False,
        domain: str = "",
    ) -> None:
        """Record a failed request through a proxy."""
        proxy.record_failure(is_block=is_block, domain=domain)

        # If proxy is now quarantined, release domain locks
        if proxy.is_quarantined:
            for d, p in list(self._domain_locks.items()):
                if p is proxy:
                    del self._domain_locks[d]

    def release_domain(self, domain: str) -> None:
        """Release a domain's sticky proxy lock."""
        self._domain_locks.pop(domain, None)

    def get_pool_stats(self) -> dict[str, Any]:
        """Get statistics for all proxy pools."""
        return {
            tier.name: {
                "total": len(proxies),
                "healthy": sum(1 for p in proxies if p.status == ProxyStatus.HEALTHY),
                "degraded": sum(1 for p in proxies if p.status == ProxyStatus.DEGRADED),
                "quarantined": sum(1 for p in proxies if p.status == ProxyStatus.QUARANTINED),
                "avg_health_score": (
                    round(sum(p.health_score for p in proxies) / len(proxies), 3)
                    if proxies else 0
                ),
            }
            for tier, proxies in self._pools.items()
        }
