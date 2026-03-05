"""
Redpanda/Kafka consumer with automatic Pydantic deserialization.

Wraps confluent-kafka Consumer to return typed Pydantic models instead
of raw bytes. Supports consumer groups for horizontal scaling.

Usage:
    consumer = ArachneConsumer(
        topics=["crawl.results"],
        group_id="result-processor",
        bootstrap_servers="localhost:19092",
    )
    for topic, event in consumer.consume(model_class=CrawlResultEvent):
        process(event)
    consumer.close()
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import TypeVar

from confluent_kafka import Consumer, KafkaError, KafkaException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ArachneConsumer:
    """Typed Kafka consumer that deserializes JSON messages into Pydantic models.

    Wraps confluent-kafka Consumer with:
    - Automatic JSON -> Pydantic deserialization
    - Consumer group support for horizontal scaling
    - Graceful error handling (malformed messages logged, not crashed)

    Args:
        topics: List of topics to subscribe to.
        group_id: Consumer group ID (multiple consumers in same group = load balancing).
        bootstrap_servers: Redpanda broker address(es).
        config: Additional confluent-kafka consumer config overrides.
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        bootstrap_servers: str = "localhost:19092",
        config: dict | None = None,
    ) -> None:
        consumer_config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
        }
        if config:
            consumer_config.update(config)

        self._consumer = Consumer(consumer_config)
        self._consumer.subscribe(topics)
        self._running = True

    def consume(
        self,
        model_class: type[T],
        timeout: float = 1.0,
    ) -> Generator[tuple[str, T], None, None]:
        """Yield (topic, model) tuples from subscribed topics.

        Blocks for up to `timeout` seconds waiting for messages.
        Automatically deserializes JSON into the given Pydantic model.
        Malformed messages are logged and skipped (no crash).

        Args:
            model_class: Pydantic model to deserialize into.
            timeout: Max seconds to wait per poll cycle.

        Yields:
            Tuple of (topic_name, deserialized_model).
        """
        while self._running:
            msg = self._consumer.poll(timeout=timeout)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # End of partition — not an error, just no more messages
                    continue
                raise KafkaException(msg.error())

            try:
                raw = json.loads(msg.value().decode())
                event = model_class.model_validate(raw)
                yield msg.topic(), event
            except (json.JSONDecodeError, Exception) as e:
                logger.error(
                    "Failed to deserialize message",
                    extra={
                        "topic": msg.topic(),
                        "partition": msg.partition(),
                        "offset": msg.offset(),
                        "error": str(e),
                    },
                )
                continue

    def stop(self) -> None:
        """Signal the consumer to stop on the next poll cycle."""
        self._running = False

    def close(self) -> None:
        """Stop consuming and release resources."""
        self._running = False
        self._consumer.close()
