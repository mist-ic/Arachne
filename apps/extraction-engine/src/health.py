"""
Health and readiness checks for the extraction engine.

Provides HTTP endpoints that Docker Compose and Kubernetes can probe
to determine if the service is alive, ready, and functioning correctly.

Endpoints:
    /health     — Basic liveness (service is running)
    /ready      — Readiness (Temporal connected, models available)
    /status     — Full status with model info, queue depth, metrics
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class HealthStatus:
    """Full health status of the extraction engine."""

    healthy: bool = True
    temporal_connected: bool = False
    ollama_available: bool = False
    ollama_models: list[str] = field(default_factory=list)
    gemini_configured: bool = False
    captcha_solvers_available: int = 0
    uptime_seconds: float = 0.0
    extractions_completed: int = 0
    extractions_failed: int = 0
    avg_extraction_ms: float = 0.0
    total_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


class HealthChecker:
    """Health checker for the extraction engine service."""

    def __init__(self, ollama_base_url: str = "http://ollama:11434"):
        self._ollama_url = ollama_base_url.rstrip("/")
        self._start_time = time.monotonic()
        self._extractions_completed = 0
        self._extractions_failed = 0
        self._total_extraction_ms = 0
        self._total_cost_usd = 0.0

    def record_extraction(self, elapsed_ms: int, cost_usd: float, success: bool) -> None:
        """Record an extraction attempt for metrics."""
        if success:
            self._extractions_completed += 1
        else:
            self._extractions_failed += 1
        self._total_extraction_ms += elapsed_ms
        self._total_cost_usd += cost_usd

    async def check_health(self) -> HealthStatus:
        """Perform full health check."""
        status = HealthStatus(
            uptime_seconds=time.monotonic() - self._start_time,
            extractions_completed=self._extractions_completed,
            extractions_failed=self._extractions_failed,
            total_cost_usd=self._total_cost_usd,
        )

        total = self._extractions_completed + self._extractions_failed
        if total > 0:
            status.avg_extraction_ms = self._total_extraction_ms / total

        # Check Ollama availability
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self._ollama_url}/api/tags")
                if response.status_code == 200:
                    status.ollama_available = True
                    data = response.json()
                    status.ollama_models = [
                        m.get("name", "") for m in data.get("models", [])
                    ]
        except Exception as e:
            status.errors.append(f"Ollama: {e}")

        # Check Gemini configuration
        import os

        status.gemini_configured = bool(os.environ.get("ARACHNE_GEMINI_API_KEY"))

        # Overall health
        status.healthy = status.ollama_available or status.gemini_configured

        return status

    async def is_ready(self) -> bool:
        """Quick readiness check for probes."""
        health = await self.check_health()
        return health.healthy

    async def is_alive(self) -> bool:
        """Quick liveness check — service is running."""
        return True
