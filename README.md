<div align="center">

# 🕷️ Arachne

**Autonomous Web Intelligence Platform**

*Production-grade anti-detection • AI-first extraction • Distributed pipeline architecture*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Moonrepo](https://img.shields.io/badge/monorepo-moonrepo-blueviolet)](https://moonrepo.dev/)

</div>

---

## What is Arachne?

Arachne is a web intelligence platform that unifies three domains no single project currently brings together:

1. **Production-grade Anti-Detection** — TLS/JA4+ spoofing, stealth browsers, behavioral simulation, CAPTCHA solving
2. **AI-First Extraction** — LLM + vision models, auto-schema discovery, multi-model routing
3. **Distributed Pipeline Architecture** — Redpanda, Temporal, PostgreSQL, ClickStack observability

## Quick Start

```bash
# Prerequisites: Docker + Docker Compose

# 1. Start the full infrastructure + app services
just up

# 2. Run Alembic migrations (first time only)
cd packages/core-models && alembic upgrade head && cd ../..

# 3. Wait ~30s for services to initialize, then run E2E demo
python examples/demo_e2e.py

# 4. Explore the system:
#    API docs + Swagger:  http://localhost:8000/docs
#    Temporal workflows:  http://localhost:8088
#    Redpanda topics:     http://localhost:8080
#    MinIO objects:       http://localhost:9001 (arachne / arachne123)

# Individual commands
just infra-health    # Check all service status
just infra-logs      # Tail infrastructure logs
just urls            # Show all service URLs
```

## Architecture

```
URL Submission → FastAPI Gateway → Temporal Workflow → HTTP Fetch
                                        ↓
                              MinIO (raw HTML storage)
                                        ↓
                              CSS/XPath Extraction
                                        ↓
                              PostgreSQL (structured data)
                                        ↓
                              Redpanda (event streaming)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13+ (backend), TypeScript (dashboard) |
| HTTP Client | `httpx` (standard), `curl_cffi` (TLS spoofing) |
| Browser Automation | Camoufox + Pydoll |
| Message Broker | Redpanda (Kafka API, no JVM) |
| Orchestration | Temporal (durable execution) |
| Database | PostgreSQL 16 (JSONB) |
| Object Storage | MinIO (S3-compatible) |
| Observability | OpenTelemetry → ClickStack |
| Monorepo | Moonrepo |
| API | FastAPI |

## Project Structure

```
arachne/
├── .moon/                        # Moonrepo workspace config
├── apps/
│   ├── api-gateway/              # FastAPI control plane
│   ├── worker-http/              # Temporal worker: HTTP fetching
│   ├── worker-stealth/           # Stealth browser worker
│   ├── extraction-engine/        # AI extraction service
│   └── dashboard/                # React+Vite dashboard
├── packages/
│   ├── core-models/              # Shared Pydantic schemas + database layer
│   ├── messaging/                # Redpanda producer/consumer
│   ├── storage/                  # MinIO client wrapper
│   ├── observability/            # OTel instrumentation
│   ├── anti-detection/           # Evasion engine
│   └── extraction/              # Extraction utilities
├── infra/                        # Docker Compose + scripts
├── docs/adr/                     # Architecture Decision Records
├── examples/                     # Demo scripts
└── benchmarks/                   # Performance benchmarks
```

## Documentation

- [Architecture Decision Records](docs/adr/) — Every major decision, documented and justified

## License

Proprietary — see [LICENSE](LICENSE). Commercial use requires a paid license.
