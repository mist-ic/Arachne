# Messaging

Redpanda producer/consumer wrappers with automatic Pydantic serialization and Zstandard compression.

Thin wrappers around `confluent-kafka` that automatically serialize/deserialize Pydantic events. Redpanda is 100% Kafka API compatible.

## Usage

```python
from arachne_messaging import ArachneProducer, ArachneConsumer, TopicConfig
```
