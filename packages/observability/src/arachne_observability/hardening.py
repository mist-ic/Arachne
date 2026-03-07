"""
Production hardening utilities for Arachne services.

Provides resilience patterns for production deployment:
    - Circuit breaker for external API calls
    - Rate limiter for API gateway
    - Graceful shutdown coordination
    - Deep health checks with dependency verification

References:
    - Phase4.md Step 6: Production hardening
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Circuit Breaker
# ============================================================================


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests flow through
    OPEN = "open"  # Circuit tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit is OPEN and request is rejected."""


class CircuitBreaker:
    """Circuit breaker pattern for external API calls.

    Prevents cascade failures when downstream services (LLM APIs,
    proxy providers, Ollama) are unhealthy.

    Usage:
        breaker = CircuitBreaker(name="ollama", failure_threshold=5)

        try:
            result = await breaker.call(lambda: ollama_client.chat(...))
        except CircuitBreakerError:
            # Circuit is open, use fallback
            result = use_remote_model()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        """
        Args:
            name: Identifier for this circuit breaker.
            failure_threshold: Consecutive failures before opening.
            recovery_timeout: Seconds to wait before half-open attempt.
            half_open_max_calls: Max calls allowed in half-open state.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout expired → transition to half-open
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit_half_open", name=self.name)
        return self._state

    async def call(self, func: Callable[..., Awaitable], *args, **kwargs) -> Any:
        """Execute a function through the circuit breaker.

        Args:
            func: Async callable to execute.

        Returns:
            Result of the function call.

        Raises:
            CircuitBreakerError: If circuit is OPEN.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitBreakerError(
                f"Circuit '{self.name}' is OPEN "
                f"(failures: {self._failure_count})"
            )

        if (
            current_state == CircuitState.HALF_OPEN
            and self._half_open_calls >= self.half_open_max_calls
        ):
            raise CircuitBreakerError(
                f"Circuit '{self.name}' is HALF_OPEN, max test calls reached"
            )

        try:
            if current_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            logger.info("circuit_closed", name=self.name, reason="recovery_succeeded")
        self._failure_count = 0
        self._success_count += 1

    def _on_failure(self) -> None:
        """Handle failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_opened",
                name=self.name,
                failures=self._failure_count,
                recovery_timeout=self.recovery_timeout,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0


# ============================================================================
# Rate Limiter (Token Bucket)
# ============================================================================


class RateLimiter:
    """Token bucket rate limiter for API request throttling.

    Usage:
        limiter = RateLimiter(rate=10, burst=20)  # 10 req/sec, burst of 20

        if limiter.allow():
            process_request()
        else:
            return 429, "Rate limit exceeded"
    """

    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: Requests per second (sustained).
            burst: Maximum burst size.
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()

    def allow(self) -> bool:
        """Check if a request is allowed and consume a token.

        Returns:
            True if request is allowed, False if rate limited.
        """
        self._refill()

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.burst),
            self._tokens + elapsed * self.rate,
        )
        self._last_refill = now


# ============================================================================
# Graceful Shutdown Coordinator
# ============================================================================


class GracefulShutdown:
    """Coordinate graceful shutdown across async workers.

    Ensures in-flight requests complete before shutdown.

    Usage:
        shutdown = GracefulShutdown()

        # In your lifespan:
        async with shutdown.guard():
            await process_request()

        # On SIGTERM:
        await shutdown.initiate(timeout=30)
    """

    def __init__(self):
        self._shutting_down = False
        self._active_count = 0
        self._lock = asyncio.Lock()
        self._all_done = asyncio.Event()
        self._all_done.set()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    class _Guard:
        def __init__(self, shutdown: GracefulShutdown):
            self._shutdown = shutdown

        async def __aenter__(self):
            async with self._shutdown._lock:
                if self._shutdown._shutting_down:
                    raise RuntimeError("Server is shutting down")
                self._shutdown._active_count += 1
                self._shutdown._all_done.clear()
            return self

        async def __aexit__(self, *exc):
            async with self._shutdown._lock:
                self._shutdown._active_count -= 1
                if self._shutdown._active_count == 0:
                    self._shutdown._all_done.set()

    def guard(self) -> _Guard:
        """Context manager that tracks active requests."""
        return self._Guard(self)

    async def initiate(self, timeout: float = 30.0) -> bool:
        """Initiate graceful shutdown.

        Args:
            timeout: Max seconds to wait for in-flight requests.

        Returns:
            True if all requests completed, False if timeout.
        """
        logger.info(
            "graceful_shutdown_initiated",
            active_requests=self._active_count,
            timeout=timeout,
        )

        self._shutting_down = True

        try:
            await asyncio.wait_for(self._all_done.wait(), timeout=timeout)
            logger.info("graceful_shutdown_complete")
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "graceful_shutdown_timeout",
                remaining_requests=self._active_count,
            )
            return False


# ============================================================================
# Deep Health Check
# ============================================================================


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    healthy: bool
    latency_ms: int = 0
    error: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Aggregated system health."""

    healthy: bool
    components: list[ComponentHealth] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": "healthy" if self.healthy else "unhealthy",
            "timestamp": self.timestamp,
            "components": {
                c.name: {
                    "status": "up" if c.healthy else "down",
                    "latency_ms": c.latency_ms,
                    "error": c.error,
                    **c.details,
                }
                for c in self.components
            },
        }


class HealthChecker:
    """Deep health check across all service dependencies.

    Checks: PostgreSQL, Temporal, Redpanda, MinIO, Ollama,
    ClickHouse, OTel Collector.

    Usage:
        checker = HealthChecker()
        checker.add_check("postgres", check_postgres)
        checker.add_check("temporal", check_temporal)

        health = await checker.check_all()
        print(health.to_dict())
    """

    def __init__(self):
        self._checks: dict[str, Callable[[], Awaitable[ComponentHealth]]] = {}

    def add_check(
        self,
        name: str,
        check_func: Callable[[], Awaitable[ComponentHealth]],
    ) -> None:
        """Register a health check function."""
        self._checks[name] = check_func

    async def check_all(self) -> SystemHealth:
        """Run all health checks concurrently."""
        results = await asyncio.gather(
            *(check() for check in self._checks.values()),
            return_exceptions=True,
        )

        components = []
        for name, result in zip(self._checks.keys(), results):
            if isinstance(result, Exception):
                components.append(ComponentHealth(
                    name=name,
                    healthy=False,
                    error=str(result),
                ))
            elif isinstance(result, ComponentHealth):
                components.append(result)

        all_healthy = all(c.healthy for c in components)

        return SystemHealth(
            healthy=all_healthy,
            components=components,
            timestamp=time.time(),
        )
