"""
Prometheus + OpenTelemetry metrics for Arachne services.

Pre-defined counters, histograms, and gauges for tracking job lifecycle,
crawl performance, extraction throughput, anti-detection evasion,
and AI model usage.

Phase 1: Prometheus metrics via /metrics endpoint.
Phase 4: OTLP export to ClickStack + Prometheus compatibility.

Scraping-specific metrics (Phase 4):
    - Anti-bot encounters and evasion success rates
    - Proxy health and selection metrics
    - LLM token usage and cost tracking
    - Redpanda consumer lag
    - Schema drift detection and repair events
    - Vision pipeline performance
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Gauge, Histogram, Info

# Service metadata
_service_info = Info("arachne_service", "Service metadata")

# =============================================================================
# Job Lifecycle Counters
# =============================================================================

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

# =============================================================================
# Crawl Performance
# =============================================================================

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

# =============================================================================
# Extraction Metrics
# =============================================================================

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

EXTRACTION_CONFIDENCE = Histogram(
    "arachne_extraction_confidence",
    "Extraction confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# =============================================================================
# Anti-Detection / Evasion Metrics (Phase 4)
# =============================================================================

ANTIBOT_ENCOUNTERS = Counter(
    "arachne_antibot_encounters_total",
    "Total anti-bot system encounters",
    ["vendor", "action"],  # vendor: cloudflare/akamai/..., action: blocked/challenged/passed
)

EVASION_SUCCESS = Counter(
    "arachne_evasion_success_total",
    "Successful evasion attempts by strategy",
    ["strategy"],  # strategy: tls_spoof, browser_stealth, proxy_rotate, captcha_solve
)

EVASION_FAILURE = Counter(
    "arachne_evasion_failure_total",
    "Failed evasion attempts by strategy",
    ["strategy"],
)

# =============================================================================
# Proxy Health Metrics (Phase 4)
# =============================================================================

PROXY_REQUESTS = Counter(
    "arachne_proxy_requests_total",
    "Total requests through proxies",
    ["proxy_provider", "status"],  # status: success/failure/timeout
)

PROXY_LATENCY = Histogram(
    "arachne_proxy_latency_seconds",
    "Proxy request latency",
    ["proxy_provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

PROXY_POOL_SIZE = Gauge(
    "arachne_proxy_pool_size",
    "Current number of healthy proxies",
    ["proxy_provider"],
)

# =============================================================================
# LLM / AI Model Metrics (Phase 4)
# =============================================================================

LLM_TOKENS_USED = Counter(
    "arachne_llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "direction"],  # direction: input/output
)

LLM_COST_USD = Counter(
    "arachne_llm_cost_usd_total",
    "Estimated LLM cost in USD",
    ["model"],
)

LLM_REQUEST_DURATION = Histogram(
    "arachne_llm_request_duration_seconds",
    "LLM API request duration",
    ["model"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

LLM_ERRORS = Counter(
    "arachne_llm_errors_total",
    "LLM API errors",
    ["model", "error_type"],
)

# =============================================================================
# Schema Drift Detection Metrics (Phase 4)
# =============================================================================

SCHEMA_DRIFT_DETECTED = Counter(
    "arachne_schema_drift_detected_total",
    "Schema drift detection events",
    ["domain", "severity"],
)

SCHEMA_AUTO_REPAIRED = Counter(
    "arachne_schema_auto_repaired_total",
    "Successful schema auto-repair events",
    ["domain"],
)

SCHEMA_REPAIR_FAILED = Counter(
    "arachne_schema_repair_failed_total",
    "Failed schema auto-repair attempts",
    ["domain"],
)

# =============================================================================
# Vision Pipeline Metrics (Phase 4)
# =============================================================================

VISION_EXTRACTION_DURATION = Histogram(
    "arachne_vision_extraction_seconds",
    "Vision pipeline extraction duration",
    ["stage"],  # stage: segmentation/detection/extraction/assembly
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

VISION_SEGMENTS_FOUND = Histogram(
    "arachne_vision_segments_count",
    "Number of segments found per screenshot",
    buckets=[1, 5, 10, 25, 50, 100],
)

# =============================================================================
# Message Queue Metrics (Phase 4)
# =============================================================================

REDPANDA_CONSUMER_LAG = Gauge(
    "arachne_redpanda_consumer_lag",
    "Redpanda consumer group lag",
    ["topic", "partition"],
)


# =============================================================================
# Initialization
# =============================================================================


def init_metrics(service_name: str = "arachne") -> None:
    """Initialize metrics with service metadata.

    In Phase 4, also initializes OTLP metrics exporter alongside
    Prometheus when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    Args:
        service_name: Name of the service for the info metric.
    """
    _service_info.info({
        "version": "0.4.0",
        "service": service_name,
    })

    # Phase 4: OTLP metrics export
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({
                "service.name": service_name,
                "service.namespace": "arachne",
            })

            exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
            reader = PeriodicExportingMetricReader(exporter, export_interval_millis=30000)
            provider = MeterProvider(resource=resource, metric_readers=[reader])
            otel_metrics.set_meter_provider(provider)

        except ImportError:
            pass  # OTel SDK not installed — Prometheus-only mode


def get_meter():
    """Get the Prometheus registry (for custom metrics).

    Note: prometheus_client uses a global registry by default.
    This function is a convenience wrapper for consistency.
    """
    from prometheus_client import REGISTRY
    return REGISTRY
