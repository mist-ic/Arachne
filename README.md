<div align="center">

# 🕷️ Arachne

**Autonomous Web Intelligence Platform**

*Production-grade anti-detection • AI-first extraction • Distributed pipeline architecture*

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Moonrepo](https://img.shields.io/badge/monorepo-moonrepo-blueviolet)](https://moonrepo.dev/)

</div>

---

## What is Arachne?

Arachne is an open-source web intelligence platform that unifies three domains no single project currently brings together:

1. **Production-grade Anti-Detection** — TLS/JA4+ spoofing, stealth browsers, behavioral simulation, CAPTCHA solving
2. **AI-First Extraction** — LLM + vision models, auto-schema discovery, multi-model routing
3. **Distributed Pipeline Architecture** — Redpanda, Temporal, PostgreSQL, ClickStack observability

## Quick Start (Phase 1)

```bash
# Start the full stack
just up

# Wait ~30s for all services to initialize, then:
python examples/demo_e2e.py

# View system state:
# - API docs:       http://localhost:8000/docs
# - Temporal UI:    http://localhost:8088
# - Redpanda:       http://localhost:8080
# - MinIO Console:  http://localhost:9001
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
| Language | Python 3.12+ (backend), TypeScript (dashboard) |
| HTTP Client | `httpx` (Phase 1), `curl_cffi` (Phase 2 — TLS spoofing) |
| Browser Automation | Camoufox + Pydoll (Phase 2) |
| Message Broker | Redpanda (Kafka API, no JVM) |
| Orchestration | Temporal (durable execution) |
| Database | PostgreSQL 16 (JSONB) |
| Object Storage | MinIO (S3-compatible) |
| Observability | OpenTelemetry → ClickStack (Phase 4) |
| Monorepo | Moonrepo |
| API | FastAPI |

## Project Structure

```
arachne/
├── .moon/                        # Moonrepo workspace config
├── apps/
│   ├── api-gateway/              # FastAPI control plane
│   ├── worker-http/              # Temporal worker: HTTP fetching
│   ├── worker-stealth/           # Stealth browser worker (Phase 2)
│   ├── extraction-engine/        # AI extraction service (Phase 3)
│   └── dashboard/                # React+Vite dashboard (Phase 4)
├── packages/
│   ├── core-models/              # Shared Pydantic schemas
│   ├── messaging/                # Redpanda producer/consumer
│   ├── storage/                  # MinIO client wrapper
│   ├── observability/            # OTel instrumentation
│   ├── anti-detection/           # Evasion engine (Phase 2)
│   └── extraction/              # Extraction utilities (Phase 3)
├── infra/                        # Docker Compose + scripts
├── docs/adr/                     # Architecture Decision Records
├── examples/                     # Demo scripts
└── benchmarks/                   # Performance benchmarks
```

## Documentation

- [Architecture Decision Records](docs/adr/) — Every major decision, documented and justified
- [Proposal](../Proposal.md) — Project vision and constraints

## License

Proprietary — see [LICENSE](LICENSE). Commercial use requires a paid license.
