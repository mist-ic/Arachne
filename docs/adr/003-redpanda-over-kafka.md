# ADR-003: Redpanda over Apache Kafka

## Status
Accepted

## Context

Arachne needs a message broker for event streaming between services (crawl requests, crawl results, extraction requests, extraction results, job status updates). The broker must:

1. Support topic-based pub/sub with partitioning (ordered per-job processing)
2. Run in Docker Compose with minimal resource overhead
3. Be production-grade (not a toy for demos)
4. Have strong client library support in Python

### Alternatives Considered

| Broker | Verdict | Why |
|---|---|---|
| **Apache Kafka** | Rejected | Requires JVM + ZooKeeper (or KRaft), heavy memory footprint (~1GB+), complex Docker Compose setup with multiple containers |
| **RabbitMQ** | Rejected | Great for task queues but wrong model for event streaming. No topic replay, no partitioned ordering guarantees |
| **Redis Streams** | Rejected | Viable but lacks schema registry, consumer group semantics are weaker, and positioning is less impressive for portfolio |
| **NATS JetStream** | Rejected | Strong contender but Kafka API compatibility means zero learning curve for any team that knows Kafka |

## Decision

Use **Redpanda** as the message broker.

Key factors:
- **100% Kafka API compatible** — same client libraries (confluent-kafka), zero code changes if migrating to real Kafka
- **Single binary, no JVM** — written in C++, thread-per-core architecture
- **Sub-millisecond tail latencies** — 10x lower p99 than Kafka
- **Simple Docker Compose** — one container, no ZooKeeper/KRaft dependency
- **Built-in Schema Registry** — Kafka Schema Registry compatible, no extra container
- **~512MB memory** — vs Kafka's 1-2GB minimum for local dev
- **Redpanda Console** — excellent built-in web UI for topic inspection

## Consequences

### Positive
- Docker Compose setup is trivially simple (one container + one UI)
- Same confluent-kafka Python client used everywhere
- Memory footprint stays manageable alongside PostgreSQL, Temporal, and MinIO
- Portfolio signal: shows awareness of modern alternatives to Kafka

### Negative
- Smaller community than Kafka (fewer Stack Overflow answers)
- Some Kafka features may lag behind (Connect, Streams API)
- Enterprise features require Redpanda licensing

### Mitigations
- Kafka API compatibility means switching to real Kafka is a config change, not a rewrite
- We only use core pub/sub features (produce, consume, consumer groups) which are fully supported
