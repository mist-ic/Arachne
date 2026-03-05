# Infrastructure

Docker Compose files and initialization scripts for the Arachne local development stack.

## Services

| Service | Port | Purpose |
|---|---|---|
| Redpanda | 9092 (Kafka), 8081 (Schema), 8082 (Proxy) | Message broker |
| Redpanda Console | 8080 | Web UI for topics |
| PostgreSQL 16 | 5432 | Relational store |
| MinIO | 9000 (API), 9001 (Console) | Object storage |
| Temporal | 7233 | Workflow orchestration |
| Temporal UI | 8088 | Workflow dashboard |
