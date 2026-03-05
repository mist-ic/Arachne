#!/usr/bin/env python3
"""
Redpanda topic auto-creation script.

Reads topic definitions from arachne_messaging.topics and creates them
in Redpanda if they don't already exist. Designed to run once on startup
(or as a Docker init container).

Usage:
    python infra/scripts/init-topics.py
    python infra/scripts/init-topics.py --bootstrap-servers localhost:19092

Requires: confluent-kafka
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from confluent_kafka.admin import AdminClient, NewTopic

# Import from the messaging package
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "packages" / "messaging" / "src"))
from arachne_messaging.topics import TOPICS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def create_topics(bootstrap_servers: str, max_retries: int = 10) -> None:
    """Create all Arachne topics in Redpanda.

    Retries connection to Redpanda with exponential backoff since the broker
    may still be starting up when this script runs.
    """
    admin = None

    for attempt in range(1, max_retries + 1):
        try:
            admin = AdminClient({"bootstrap.servers": bootstrap_servers})
            # Test connection by listing topics
            metadata = admin.list_topics(timeout=5)
            existing = set(metadata.topics.keys())
            logger.info(f"Connected to Redpanda. Existing topics: {existing}")
            break
        except Exception as e:
            wait = min(2 ** attempt, 30)
            logger.warning(f"Attempt {attempt}/{max_retries}: Cannot connect to Redpanda ({e}). Retrying in {wait}s...")
            time.sleep(wait)
    else:
        logger.error(f"Failed to connect to Redpanda after {max_retries} attempts")
        sys.exit(1)

    # Determine which topics need to be created
    to_create = []
    for config in TOPICS.values():
        if config.name not in existing:
            to_create.append(
                NewTopic(
                    topic=config.name,
                    num_partitions=config.partitions,
                    config={"retention.ms": str(config.retention_ms)},
                )
            )
            logger.info(f"  Will create: {config.name} (partitions={config.partitions})")
        else:
            logger.info(f"  Already exists: {config.name}")

    if not to_create:
        logger.info("All topics already exist. Nothing to do.")
        return

    # Create topics
    futures = admin.create_topics(to_create)
    for topic_name, future in futures.items():
        try:
            future.result()  # Block until topic is created
            logger.info(f"  Created: {topic_name}")
        except Exception as e:
            logger.error(f"  Failed to create {topic_name}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Arachne Redpanda topics")
    parser.add_argument(
        "--bootstrap-servers",
        default="localhost:19092",
        help="Redpanda broker address (default: localhost:19092)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=10,
        help="Max connection retries (default: 10)",
    )
    args = parser.parse_args()

    logger.info(f"Creating Arachne topics on {args.bootstrap_servers}...")
    create_topics(args.bootstrap_servers, args.max_retries)
    logger.info("Topic initialization complete.")


if __name__ == "__main__":
    main()
