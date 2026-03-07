"""
Structured JSON logging via structlog + optional OTLP log export.

Why structlog over plain logging:
- JSON output by default (machine-parseable, ClickStack ingest)
- Automatic context binding (add job_id once, it appears on every log)
- Processors chain (add timestamps, log levels, caller info automatically)
- Compatible with standard logging (structlog wraps stdlib logger)

Phase 4 enhancement: OTLP log export to ClickStack when
OTEL_EXPORTER_OTLP_ENDPOINT is set.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(
    log_level: str = "INFO",
    *,
    json_output: bool = False,
) -> None:
    """Configure structlog for structured logging.

    In development: ConsoleRenderer for human-readable output.
    In production:  JSONRenderer for ClickStack ingest.
    Phase 4:        Optional OTLP log export alongside console/JSON.

    Args:
        log_level: Minimum log level to output.
        json_output: Force JSON output (auto-detected via OTEL env var).
    """
    # Auto-detect production mode from OTLP env var
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    is_production = json_output or otlp_endpoint is not None

    # Shared processors for both structlog and stdlib logging
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,  # Merge context (job_id, etc.)
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Choose renderer based on environment
    if is_production:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()  # Human-readable in dev

    # Configure stdlib logging to use structlog formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("confluent_kafka").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Phase 4: Setup OTLP log export
    if otlp_endpoint:
        _setup_otlp_log_export(otlp_endpoint)


def _setup_otlp_log_export(endpoint: str) -> None:
    """Configure OTLP log export to ClickStack.

    Adds an OTLP log handler that sends structured logs to the
    OpenTelemetry Collector, which routes them to ClickHouse.
    """
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource

        service_name = os.environ.get("OTEL_SERVICE_NAME", "arachne")

        resource = Resource.create({
            "service.name": service_name,
            "service.namespace": "arachne",
        })

        exporter = OTLPLogExporter(endpoint=endpoint, insecure=True)
        processor = BatchLogRecordProcessor(exporter)
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(processor)
        set_logger_provider(provider)

        # Add OTLP handler to root logger
        otlp_handler = LoggingHandler(
            level=logging.DEBUG,
            logger_provider=provider,
        )
        logging.getLogger().addHandler(otlp_handler)

    except ImportError:
        # OTel log SDK not installed — skip silently
        pass


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with the given name.

    Usage:
        logger = get_logger(__name__)
        logger.info("Job started", job_id="abc-123", url="https://...")
    """
    return structlog.get_logger(name)
