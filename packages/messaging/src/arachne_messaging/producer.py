"""
Redpanda/Kafka producer with automatic Pydantic serialization.

Wraps confluent-kafka Producer so services publish typed Pydantic events
without manually calling model_dump_json(). All messages are keyed by
job_id for partition-level ordering.

Usage:
    producer = ArachneProducer(bootstrap_servers="localhost:19092")
    producer.publish("crawl.requests", key=str(job_id), event=crawl_event)
    producer.close()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from confluent_kafka import Producer

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ArachneProducer:
    """Typed Kafka producer that serializes Pydantic models to JSON.

    Messages are published synchronously (flush after each produce) in
    Phase 1 for simplicity. Phase 2+ can switch to batched async delivery
    for higher throughput.

    Args:
        bootstrap_servers: Redpanda broker address(es).
        config: Additional confluent-kafka producer config overrides.
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:19092",
        config: dict | None = None,
    ) -> None:
        producer_config = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "arachne-producer",
            # Delivery reliability
            "acks": "all",
            "enable.idempotence": True,
            # Compression
            "compression.type": "zstd",
        }
        if config:
            producer_config.update(config)

        self._producer = Producer(producer_config)

    def publish(
        self,
        topic: str,
        key: str,
        event: BaseModel,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish a Pydantic event to a Redpanda topic.

        The event is serialized to JSON bytes. The key (typically job_id)
        determines the partition, ensuring ordered delivery per job.

        Args:
            topic: Target topic name (e.g. "crawl.requests").
            key: Partition key (typically str(job_id)).
            event: Pydantic model instance to serialize.
            headers: Optional message headers (e.g. trace context).
        """
        kafka_headers = (
            [(k, v.encode()) for k, v in headers.items()] if headers else None
        )

        self._producer.produce(
            topic=topic,
            key=key.encode(),
            value=event.model_dump_json().encode(),
            headers=kafka_headers,
            on_delivery=self._on_delivery,
        )
        self._producer.flush()

    def _on_delivery(self, err, msg) -> None:
        """Callback invoked on message delivery (success or failure)."""
        if err is not None:
            logger.error(
                "Message delivery failed",
                extra={"topic": msg.topic(), "error": str(err)},
            )
        else:
            logger.debug(
                "Message delivered",
                extra={
                    "topic": msg.topic(),
                    "partition": msg.partition(),
                    "offset": msg.offset(),
                },
            )

    def close(self) -> None:
        """Flush remaining messages and clean up."""
        remaining = self._producer.flush(timeout=10)
        if remaining > 0:
            logger.warning(f"{remaining} messages were not delivered on close")
