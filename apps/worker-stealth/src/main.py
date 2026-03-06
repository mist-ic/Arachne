"""
Temporal worker entry point for the stealth browser worker.

Starts the Temporal worker that listens on the "scrape-stealth" task queue
and processes StealthScrapeWorkflow executions. This worker handles jobs
that were escalated from worker-http due to anti-bot blocking.

Browser backends (Camoufox, Pydoll) are heavier than HTTP clients,
so this worker runs with lower concurrency than worker-http.

Usage:
    python -m src.main

    # Or with custom config via environment variables:
    ARACHNE_BROWSER_BACKEND=pydoll python -m src.main
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from activities import fetch_with_browser, store_browser_cookies
from config import StealthWorkerConfig
from workflows.stealth_scrape_workflow import StealthScrapeWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Start the Temporal stealth worker.

    The worker registers:
    - Workflows: StealthScrapeWorkflow (browser-based scraping)
    - Activities: fetch_with_browser, store_browser_cookies
    """
    config = StealthWorkerConfig()
    logger.info("Starting Arachne Stealth worker")
    logger.info(f"  Temporal:   {config.temporal_address}")
    logger.info(f"  Queue:      {config.temporal_task_queue}")
    logger.info(f"  Backend:    {config.browser_backend}")
    logger.info(f"  Headless:   {config.browser_headless}")
    logger.info(f"  Concurrency: {config.max_concurrent_activities} activities")

    # Connect to Temporal server
    client = await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
    )
    logger.info("Connected to Temporal")

    # Create and run the worker
    worker = Worker(
        client,
        task_queue=config.temporal_task_queue,
        workflows=[StealthScrapeWorkflow],
        activities=[
            fetch_with_browser,
            store_browser_cookies,
        ],
        max_concurrent_activities=config.max_concurrent_activities,
    )

    logger.info(f"Worker listening on queue '{config.temporal_task_queue}'...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
