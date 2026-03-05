"""
arachne_messaging — Redpanda producer/consumer with Pydantic serialization.

Thin wrappers around confluent-kafka that automatically serialize/deserialize
Pydantic models. Redpanda is 100% Kafka API compatible, so we use the standard
confluent-kafka client library.

Usage:
    from arachne_messaging import ArachneProducer, ArachneConsumer, TopicConfig
"""

from arachne_messaging.producer import ArachneProducer
from arachne_messaging.consumer import ArachneConsumer
from arachne_messaging.topics import TOPICS, TopicConfig

__all__ = [
    "ArachneProducer",
    "ArachneConsumer",
    "TopicConfig",
    "TOPICS",
]
