# Infrastructure

Docker Compose files and initialization scripts for the Arachne local development stack.

## Services

| Service | Port | Purpose |
|---|---|---|
| API Gateway | 8000 | FastAPI REST API |
| Worker HTTP | *(internal)* | Temporal activity worker |
| Redpanda | 19092 (Kafka), 18081 (Schema), 18082 (Proxy) | Message broker |
| Redpanda Console | 8080 | Web UI for topics |
| PostgreSQL 16 | 5432 | Application data |
| PostgreSQL 16 (Temporal) | 5433 | Temporal backend |
| MinIO | 9000 (API), 9001 (Console) | Object storage |
| Temporal | 7233 | Workflow orchestration |
| Temporal UI | 8088 | Workflow dashboard |

## Quick Start

```bash
# Bring everything up (infrastructure + app services)
docker compose -f infra/docker-compose.yml up -d

# Tear down (keep data)
docker compose -f infra/docker-compose.yml down

# Tear down (wipe volumes)
docker compose -f infra/docker-compose.yml down -v
```
