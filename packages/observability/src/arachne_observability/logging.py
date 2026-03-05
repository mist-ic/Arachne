"""
Structured JSON logging via structlog.

Why structlog over plain logging:
- JSON output by default (machine-parseable, ClickStack ingest)
- Automatic context binding (add job_id once, it appears on every log)
- Processors chain (add timestamps, log levels, caller info automatically)
- Compatible with standard logging (structlog wraps stdlib logger)
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON-formatted structured logging.

    In development, uses ConsoleRenderer for human-readable output.
    In production (when exported to ClickStack), uses JSONRenderer.

    Args:
        log_level: Minimum log level to output.
    """
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

    # Configure stdlib logging to use structlog formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),  # Human-readable in dev
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("confluent_kafka").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with the given name.

    Usage:
        logger = get_logger(__name__)
        logger.info("Job started", job_id="abc-123", url="https://...")
    """
    return structlog.get_logger(name)
