"""
Prometheus metrics for Arachne services.

Pre-defined counters and histograms for tracking job lifecycle,
crawl performance, and extraction throughput. These metrics are
exported via the /metrics endpoint (added in Phase 4 with full
ClickStack integration).

Phase 1: Metrics are created and tracked in-memory.
Phase 4: Scraped by Prometheus / VictoriaMetrics → Grafana dashboards.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Info

# Service metadata
_service_info = Info("arachne_service", "Service metadata")

# Job lifecycle counters
JOBS_CREATED = Counter(
    "arachne_jobs_created_total",
    "Total jobs submitted to the system",
    ["priority"],
)

JOBS_COMPLETED = Counter(
    "arachne_jobs_completed_total",
    "Total jobs that completed successfully",
)

JOBS_FAILED = Counter(
    "arachne_jobs_failed_total",
    "Total jobs that failed after all retries",
    ["error_type"],
)

# Crawl performance histograms
CRAWL_DURATION = Histogram(
    "arachne_crawl_duration_seconds",
    "Time to fetch a URL",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0],
)

CRAWL_RESPONSE_SIZE = Histogram(
    "arachne_crawl_response_bytes",
    "Size of crawled HTML responses",
    buckets=[1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000],
)

# Extraction metrics
EXTRACTION_DURATION = Histogram(
    "arachne_extraction_duration_seconds",
    "Time to extract data from HTML",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
)

EXTRACTION_FIELDS = Histogram(
    "arachne_extraction_fields_count",
    "Number of fields extracted per job",
    buckets=[1, 5, 10, 25, 50, 100],
)


def init_metrics(service_name: str = "arachne") -> None:
    """Initialize metrics with service metadata.

    Args:
        service_name: Name of the service for the info metric.
    """
    _service_info.info({
        "version": "0.1.0",
        "service": service_name,
    })


def get_meter():
    """Get the Prometheus registry (for custom metrics).

    Note: prometheus_client uses a global registry by default.
    This function is a convenience wrapper for consistency.
    """
    from prometheus_client import REGISTRY
    return REGISTRY
