"""
Extraction engine — Temporal worker entry point.

Listens on the "extract-ai" task queue and executes AI extraction,
schema discovery, and CAPTCHA solving activities.

Run: python -m src.main
"""

from __future__ import annotations

import asyncio
import logging

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    discover_page_schema,
    extract_with_llm,
    solve_page_captcha,
)
from config import ExtractionEngineSettings


def configure_logging(level: str) -> None:
    """Configure structlog + stdlib logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def main() -> None:
    """Start the Temporal worker for AI extraction activities."""
    settings = ExtractionEngineSettings()
    configure_logging(settings.log_level)

    logger = structlog.get_logger("extraction-engine")
    logger.info(
        "starting_extraction_engine",
        temporal_address=settings.temporal_address,
        task_queue=settings.task_queue,
        default_model=settings.default_model,
        cost_mode=settings.cost_mode,
        ollama_url=settings.ollama_base_url,
        has_gemini_key=bool(settings.gemini_api_key),
        has_openai_key=bool(settings.openai_api_key),
        has_anthropic_key=bool(settings.anthropic_api_key),
    )

    # Configure LiteLLM with API keys
    try:
        import litellm

        if settings.gemini_api_key:
            import os
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.openai_api_key:
            import os
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.anthropic_api_key:
            import os
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        # Suppress LiteLLM's verbose logging
        litellm.suppress_debug_info = True
    except ImportError:
        logger.warning("litellm_not_installed")

    # Connect to Temporal
    client = await Client.connect(settings.temporal_address)
    logger.info("temporal_connected")

    # Start the worker
    worker = Worker(
        client,
        task_queue=settings.task_queue,
        activities=[
            extract_with_llm,
            discover_page_schema,
            solve_page_captcha,
        ],
        max_concurrent_activities=settings.max_concurrent_activities,
    )

    logger.info(
        "worker_started",
        task_queue=settings.task_queue,
        max_concurrent=settings.max_concurrent_activities,
        activities=["extract_with_llm", "discover_page_schema", "solve_page_captcha"],
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
