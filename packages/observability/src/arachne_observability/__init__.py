"""
arachne_observability — Structured logging, OpenTelemetry, and Prometheus metrics.

Provides a single init_observability() call that sets up everything:
- structlog for JSON-formatted structured logging
- OpenTelemetry SDK with OTLP export (Phase 4: ClickStack backend)
- Prometheus metrics for request tracking
- FastAPI and httpx auto-instrumentation

Usage:
    from arachne_observability import init_observability, get_logger, get_meter

    init_observability(service_name="api-gateway")
    logger = get_logger("my_module")
    meter = get_meter()
"""

from arachne_observability.logging import configure_logging, get_logger
from arachne_observability.tracing import init_tracing
from arachne_observability.metrics import get_meter, init_metrics, JOBS_CREATED, JOBS_COMPLETED, JOBS_FAILED

__all__ = [
    "init_observability",
    "configure_logging",
    "get_logger",
    "init_tracing",
    "init_metrics",
    "get_meter",
    "JOBS_CREATED",
    "JOBS_COMPLETED",
    "JOBS_FAILED",
]


def init_observability(
    service_name: str = "arachne",
    otlp_endpoint: str | None = None,
    log_level: str = "INFO",
) -> None:
    """Initialize all observability systems.

    Call once at application startup. Sets up logging, tracing, and metrics.

    Args:
        service_name: Name used in traces and metrics (e.g. "api-gateway").
        otlp_endpoint: OTLP collector endpoint. None = console export only.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
    """
    configure_logging(log_level=log_level)
    init_tracing(service_name=service_name, otlp_endpoint=otlp_endpoint)
    init_metrics(service_name=service_name)
