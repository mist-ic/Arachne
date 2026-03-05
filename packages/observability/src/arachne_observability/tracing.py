"""
OpenTelemetry distributed tracing setup.

Instruments the application with distributed traces that flow across
service boundaries (API gateway → Temporal → worker → MinIO → Redpanda).

Phase 1: Console exporter (logs trace data to stdout for dev)
Phase 4: OTLP gRPC exporter to ClickStack (Grafana Tempo backend)
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)


def init_tracing(
    service_name: str = "arachne",
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: Name for the service in trace data.
        otlp_endpoint: OTLP collector endpoint (e.g. "http://otel-collector:4317").
                       If None, uses ConsoleSpanExporter for local dev.
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": "development",
        }
    )

    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        # Phase 4: Export to ClickStack via OTLP gRPC
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        # Phase 1: Console export for development
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer for creating custom spans.

    Usage:
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("process_job") as span:
            span.set_attribute("job_id", job_id)
            ...
    """
    return trace.get_tracer(name)
