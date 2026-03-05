"""
Temporal worker entry point.

Starts the Temporal worker that listens on the "scrape-http" task queue
and processes ScrapeWorkflow executions. Multiple instances can run in
parallel for horizontal scaling — Temporal handles work distribution.

Usage:
    python -m src.main

    # Or with custom config via environment variables:
    ARACHNE_TEMPORAL_ADDRESS=temporal:7233 python -m src.main
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    fetch_url,
    publish_crawl_result,
    record_crawl_attempt,
    store_raw_html,
    update_job_status,
)
from config import WorkerConfig
from workflows.scrape_workflow import ScrapeWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """Start the Temporal worker.

    The worker registers:
    - Workflows: ScrapeWorkflow (orchestrates the full pipeline)
    - Activities: fetch_url, store_raw_html, publish_crawl_result,
                  update_job_status (individual units of work)

    The task queue "scrape-http" is the channel through which work flows.
    The API gateway starts workflows on this queue, and this worker
    picks them up and executes them.
    """
    config = WorkerConfig()
    logger.info(f"Starting Arachne HTTP worker")
    logger.info(f"  Temporal:  {config.temporal_address}")
    logger.info(f"  Queue:     {config.temporal_task_queue}")
    logger.info(f"  Redpanda:  {config.redpanda_brokers}")
    logger.info(f"  MinIO:     {config.minio_endpoint}")
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
        workflows=[ScrapeWorkflow],
        activities=[
            fetch_url,
            store_raw_html,
            publish_crawl_result,
            update_job_status,
            record_crawl_attempt,
        ],
        max_concurrent_activities=config.max_concurrent_activities,
    )

    logger.info(f"Worker listening on queue '{config.temporal_task_queue}'...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
