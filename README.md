<div align="center">

# 🕷️ Arachne

### Autonomous Web Intelligence Platform

*The open-source project that unifies production-grade anti-detection, AI-first extraction,<br>and distributed pipeline architecture — three domains no single project brings together.*

<br>

[![Python 3.13+](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Temporal](https://img.shields.io/badge/Temporal-Durable_Workflows-000000?style=for-the-badge&logo=temporal&logoColor=white)](https://temporal.io)
[![Redpanda](https://img.shields.io/badge/Redpanda-Event_Streaming-E2003E?style=for-the-badge&logo=redpanda&logoColor=white)](https://redpanda.com)
[![Moonrepo](https://img.shields.io/badge/Moonrepo-Monorepo-7C3AED?style=for-the-badge)](https://moonrepo.dev)
[![License](https://img.shields.io/badge/License-Proprietary-EF4444?style=for-the-badge)](LICENSE)

<br>

**[Quick Start](#-quick-start)** · **[Architecture](#-architecture)** · **[Key Features](#-key-features)** · **[Tech Stack](#-tech-stack)** · **[Documentation](#-documentation)**

</div>

---

## The Problem

The web scraping ecosystem in 2026 is fragmented across three domains:

| Domain | The Status Quo | Arachne's Approach |
|--------|---------------|-------------------|
| **Anti-Detection** | Most scrapers use `requests` + `BeautifulSoup` and get 403'd by TLS fingerprinting, behavioral ML, and polymorphic JS challenges | JA4+ TLS spoofing via `curl_cffi`, stealth browsers (Camoufox + Pydoll), behavioral simulation, 4-tier adaptive evasion with automatic escalation |
| **AI Extraction** | Tools like Crawl4AI and Firecrawl assume you can already *get* the HTML — none handle evasion | LLM schema-bound extraction via `instructor`, multi-model routing (local → cloud → frontier), auto-schema discovery, vision CAPTCHA solving |
| **Distributed Scraping** | Production-scale systems exist only as closed-source SaaS ($50-500+/mo) | Open-source pipeline: Redpanda streams, Temporal durable workflows, PostgreSQL + MinIO storage, full observability |

**No open-source project occupies the intersection of all three.** That's the gap Arachne fills.

---

## 🚀 Quick Start

```bash
# Prerequisites: Docker, Docker Compose, just (command runner)
# Optional: Gemini API key for AI extraction, GPU for local models

# 1. Clone and configure
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY (optional)

# 2. Start the full distributed system (one command)
just up

# 3. Run database migrations (first time only)
cd packages/core-models && alembic upgrade head && cd ../..

# 4. Wait ~30s for services to spin up, then run the E2E demo
python examples/demo_e2e.py
```

### What Happens

The demo submits a URL through the **API Gateway**, which triggers a **Temporal durable workflow**. The workflow fetches the page via `httpx` (or escalates through stealth tiers if blocked), stores raw HTML in **MinIO** (Claim-Check pattern), streams events through **Redpanda**, runs extraction (CSS/XPath or LLM-based), and persists structured JSON to **PostgreSQL**.

### Service Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| **API Gateway** | [localhost:8000/docs](http://localhost:8000/docs) | REST API with Swagger UI |
| **Temporal UI** | [localhost:8088](http://localhost:8088) | Workflow execution monitoring |
| **Redpanda Console** | [localhost:8080](http://localhost:8080) | Event stream inspection |
| **MinIO Console** | [localhost:9001](http://localhost:9001) | Object storage browser (`arachne` / `arachne123`) |
| **Ollama** | [localhost:11434](http://localhost:11434) | Local LLM inference server |

---

## 🏗️ Architecture

```
                                    ┌──────────────────────────────────────────────────────────┐
                                    │                    CONTROL PLANE                          │
                                    │                                                          │
   ┌──────────┐    REST/WS         │  ┌──────────────┐        ┌──────────────────────┐       │
   │  Client   │──────────────────▶│  │  API Gateway  │──────▶│  PostgreSQL           │       │
   └──────────┘                    │  │  (FastAPI)     │       │  (jobs, schemas,      │       │
                                    │  └───────┬───────┘       │   results, attempts)  │       │
                                    │          │               └──────────────────────┘       │
                                    └──────────┼──────────────────────────────────────────────┘
                                               │ Start workflow
                                               ▼
                                    ┌──────────────────┐
                                    │     Temporal      │
                                    │  (Orchestration)  │
                                    └────┬────────┬─────┘
                                         │        │
                        ┌────────────────┘        └────────────────┐
                        ▼                                          ▼
          ┌──────────────────────┐                   ┌──────────────────────┐
          │    worker-http       │                   │   worker-stealth     │
          │  ┌────────────────┐  │                   │  ┌────────────────┐  │
          │  │  httpx fetch   │  │  escalate on 403  │  │  Camoufox      │  │
          │  │  (Tier 1-2)    │──┼──────────────────▶│  │  Pydoll        │  │
          │  └────────────────┘  │                   │  │  (Tier 3-4)    │  │
          └──────────┬───────────┘                   └────────┬───────────┘
                     │                                         │
                     │           ┌──────────┐                  │
                     └──────────▶│  MinIO   │◀─────────────────┘
                      raw HTML   │ (S3 obj  │   raw HTML + screenshots
                     (Claim-Check)│ storage)│
                                 └────┬─────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
             ┌───────────────────┐   ┌────────────────────────┐
             │   CSS/XPath       │   │   extraction-engine    │
             │   Extraction      │   │  ┌──────────────────┐  │
             │   (worker-http)   │   │  │ Preprocessor     │  │
             └────────┬──────────┘   │  │ LLM Extractor    │  │
                      │              │  │ Model Router     │  │
                      │              │  │ Schema Discovery │  │
                      │              │  │ CAPTCHA Solver   │  │
                      │              │  └──────────────────┘  │
                      │              └───────────┬────────────┘
                      │                          │
                      ▼                          ▼
              ┌──────────────┐          ┌──────────────┐
              │  Redpanda    │          │   Ollama     │
              │  (events)    │          │  (local LLM) │
              └──────────────┘          └──────────────┘
```

---

## ✨ Key Features

### 🛡️ Anti-Detection Engine

The evasion engine implements a **4-tier adaptive router** that automatically escalates stealth based on target defenses:

| Tier | Method | When Used |
|------|--------|-----------|
| **Tier 1** | `httpx` with randomized headers | No protection detected |
| **Tier 2** | `curl_cffi` with JA4+ TLS spoofing | TLS fingerprint rejection (JA3/JA4) |
| **Tier 3** | Camoufox stealth browser | JavaScript challenges, bot detection |
| **Tier 4** | Pydoll + behavioral simulation + CAPTCHA solving | Advanced ML-based detection, CAPTCHAs |

**Components:** [Evasion Router](packages/anti-detection/src/arachne_stealth/evasion_router.py) · [TLS Spoofing](packages/anti-detection/src/arachne_stealth/http_client.py) · [Browser Backends](packages/anti-detection/src/arachne_stealth/backends/) · [Fingerprint Observatory](packages/anti-detection/src/arachne_stealth/fingerprint.py) · [Cookie Manager](packages/anti-detection/src/arachne_stealth/cookie_manager.py) · [Proxy Manager](packages/anti-detection/src/arachne_stealth/proxy_manager.py) · [Vendor Detection](packages/anti-detection/src/arachne_stealth/vendor_detect.py) · [Behavioral Simulation](packages/anti-detection/src/arachne_stealth/behavior.py)

---

### 🧠 AI Extraction Engine

The extraction pipeline transforms raw HTML into structured data using LLMs:

```
Raw HTML → DOM Pruning → HTML-to-Markdown (5-10x token reduction)
                                    ↓
                          Context-aware Chunking
                          (table preservation, section splits)
                                    ↓
                          ComplexityEstimator (no LLM call)
                                    ↓
                          Model Router (cost/accuracy/SLO)
                          ↓           ↓            ↓
                       Local       Fast Cloud    Frontier
                      (Ollama)     (Flash)       (Pro)
                          ↓
                   instructor + Pydantic
                   (schema-bound extraction)
                          ↓
                   Conditional reattempt
                   (on empty/NA fields)
                          ↓
                   ExtractionOutput
                   (data + cost + confidence + provenance)
```

| Capability | Implementation |
|-----------|---------------|
| **HTML Preprocessing** | Semantic DOM pruning, link-to-citation conversion, BM25 relevance filtering |
| **Schema-Bound Extraction** | `instructor` + `LiteLLM` → validated Pydantic models with anti-hallucination prompts |
| **Multi-Model Routing** | ComplexityEstimator → 3-tier cascade: Local (free) → Fast ($0.10/M) → Frontier ($1.25/M) |
| **Auto-Schema Discovery** | Pure LLM analysis + hybrid DOM repeated-subtree detection → dynamic `create_model()` |
| **CAPTCHA Solving** | Local: Qwen3-VL via Ollama (free). External: 2Captcha + CapSolver. Cascading fallback chain |
| **Cost Control** | Per-page cost ceiling, per-domain model history, cost mode selection (minimize/balanced/accuracy) |

**Components:** [Preprocessor](packages/extraction/src/arachne_extraction/preprocessor.py) · [Chunker](packages/extraction/src/arachne_extraction/chunker.py) · [LLM Extractor](packages/extraction/src/arachne_extraction/llm_extractor.py) · [Model Router](packages/extraction/src/arachne_extraction/model_router.py) · [Schema Discovery](packages/extraction/src/arachne_extraction/schema_discovery.py) · [CAPTCHA Solver](packages/extraction/src/arachne_extraction/captcha/)

---

### ⚡ Distributed Pipeline

Every scrape request flows through a durable, event-driven pipeline:

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Gateway** | FastAPI | REST API, job submission, real-time status |
| **Orchestration** | Temporal | Durable workflows with automatic retry, timeout, compensation |
| **Message Broker** | Redpanda | Event streaming (crawl.requests, crawl.results, extraction.*) |
| **Object Storage** | MinIO | Raw HTML + extraction results via Claim-Check pattern |
| **Database** | PostgreSQL 16 | Jobs, schemas, results, crawl attempts (JSONB) |
| **Local AI** | Ollama | Local LLM/VLM inference (free, GPU-accelerated) |

---

## 🔧 Tech Stack

| Layer | Technology | Why This |
|-------|-----------|----------|
| **Language** | Python 3.13+, TypeScript | Backend + AI/ML in Python; dashboard in TS |
| **HTTP Client** | `httpx` + `curl_cffi` | Standard requests + JA4+ TLS fingerprint spoofing |
| **Browsers** | Camoufox, Pydoll | Anti-fingerprint Firefox fork + CDP Chrome automation |
| **LLM Framework** | `instructor` + `LiteLLM` | Schema-bound Pydantic extraction, provider-agnostic |
| **Message Broker** | Redpanda | Kafka API compatibility, zero-JVM, sub-ms latency |
| **Orchestration** | Temporal | Durable execution, automatic retries, workflow versioning |
| **Database** | PostgreSQL 16 | JSONB for flexible schemas, Alembic migrations |
| **Object Storage** | MinIO | S3-compatible, self-hosted, Claim-Check pattern |
| **Local Models** | Ollama | Run Qwen3, Gemma3, vision models locally with GPU |
| **Containerization** | Docker Compose | One-command full-stack setup |
| **Monorepo** | Moonrepo | Cross-language task orchestration for Python + TypeScript |
| **API** | FastAPI | Auto-generated OpenAPI docs, async, type-safe |
| **Task Runner** | just | Cross-platform command runner (Makefile alternative) |

---

## 📁 Project Structure

```
arachne/
├── apps/
│   ├── api-gateway/              # FastAPI REST API + job management
│   ├── worker-http/              # Temporal worker: HTTP fetching + CSS/XPath extraction
│   ├── worker-stealth/           # Temporal worker: stealth browser sessions
│   ├── extraction-engine/        # Temporal worker: AI extraction + schema discovery
│   └── dashboard/                # React + Vite monitoring dashboard
│
├── packages/
│   ├── anti-detection/           # 🛡️ Evasion engine (11 modules)
│   │   ├── evasion_router.py     #     Adaptive 4-tier escalation router
│   │   ├── http_client.py        #     curl_cffi TLS spoofing wrapper
│   │   ├── backends/             #     Camoufox + Pydoll browser backends
│   │   ├── fingerprint.py        #     TLS/JA4+ fingerprint observatory
│   │   ├── behavior.py           #     Human behavioral simulation
│   │   ├── vendor_detect.py      #     Cloudflare/Akamai/PerimeterX detection
│   │   ├── cookie_manager.py     #     Cross-session cookie persistence
│   │   ├── proxy_manager.py      #     Proxy rotation with health tracking
│   │   └── profiles.py           #     Browser + device fingerprint profiles
│   │
│   ├── extraction/               # 🧠 AI extraction engine (8 modules)
│   │   ├── preprocessor.py       #     DOM pruning, HTML→Markdown, BM25
│   │   ├── chunker.py            #     Context-aware chunking
│   │   ├── llm_extractor.py      #     instructor + LiteLLM extraction
│   │   ├── model_router.py       #     Multi-model routing + cascade
│   │   ├── schema_discovery.py   #     Auto-schema via LLM/DOM analysis
│   │   └── captcha/              #     CAPTCHA detection + solving
│   │
│   ├── core-models/              # Pydantic schemas + SQLAlchemy + Alembic
│   ├── messaging/                # Redpanda producer/consumer
│   ├── storage/                  # MinIO client wrapper
│   └── observability/            # OpenTelemetry instrumentation
│
├── infra/
│   ├── docker-compose.yml        # Full-stack local environment
│   └── scripts/                  # Infrastructure setup + health checks
│
├── docs/adr/                     # 8 Architecture Decision Records
├── examples/                     # E2E demo scripts
├── benchmarks/                   # Performance benchmarks
└── justfile                      # Development command runner
```

---

## 📚 Documentation

### Architecture Decision Records

Every significant architectural decision is documented and justified:

| ADR | Decision |
|-----|----------|
| [001](docs/adr/001-moonrepo-for-monorepo.md) | Moonrepo for monorepo management |
| [002](docs/adr/002-bun-over-pnpm.md) | Bun over pnpm for JS/TS toolchain |
| [003](docs/adr/003-redpanda-over-kafka.md) | Redpanda over Apache Kafka |
| [004](docs/adr/004-temporal-for-orchestration.md) | Temporal for workflow orchestration |
| [005](docs/adr/005-claim-check-for-large-payloads.md) | Claim-Check pattern for large payloads |
| [006](docs/adr/006-curl-cffi-for-tls-spoofing.md) | curl_cffi for TLS fingerprint spoofing |
| [007](docs/adr/007-adaptive-evasion-router.md) | Adaptive 4-tier evasion router |
| [008](docs/adr/008-multi-model-extraction-routing.md) | Multi-model extraction routing with cascade |

### Package Documentation

| Package | README |
|---------|--------|
| [anti-detection](packages/anti-detection/) | Evasion engine, browser backends, fingerprinting |
| [extraction](packages/extraction/) | AI extraction, model routing, CAPTCHA solving |
| [core-models](packages/core-models/) | Shared schemas, database layer, migrations |
| [messaging](packages/messaging/) | Redpanda producer/consumer |
| [storage](packages/storage/) | MinIO client wrapper |
| [observability](packages/observability/) | OpenTelemetry instrumentation |

### Service Documentation

| Service | README |
|---------|--------|
| [api-gateway](apps/api-gateway/) | FastAPI REST API |
| [worker-http](apps/worker-http/) | HTTP fetching + CSS/XPath extraction worker |
| [worker-stealth](apps/worker-stealth/) | Stealth browser worker |
| [extraction-engine](apps/extraction-engine/) | AI extraction Temporal worker |

---

## 🧪 Development

```bash
# Start infrastructure only (no app services)
just infra-up

# Start everything
just up

# Check service health
just infra-health

# View logs
just infra-logs

# Run tests
just test

# Format + lint
just fmt
just lint

# Show all service URLs
just urls

# Reset everything (destroys all data)
just infra-reset
```

### Environment Variables

Copy `.env.example` and configure:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key (for AI extraction) |
| `ARACHNE_COST_MODE` | Model routing: `minimize` / `balanced` / `accuracy` |
| `ARACHNE_DEFAULT_MODEL` | Default LiteLLM model (e.g., `gemini/gemini-2.5-flash`) |

---

## 🏛️ Design Philosophy

This project was designed from three independent research analyses, cross-synthesized into a unified architecture. Every technology decision is documented, justified, and defensible:

- **Best-in-class everything** — We pick whatever is genuinely the best tool regardless of familiarity or popularity
- **No half-measures** — Complete implementations of each system, not proof-of-concept stubs
- **Full observability** — Every request can be traced across the entire distributed pipeline
- **Cost-aware AI** — Multi-model routing ensures bulk simple pages cost $0 (local models) while complex pages get frontier accuracy
- **Adaptive evasion** — Start cheap, escalate automatically. Don't waste a stealth browser on a site that a simple HTTP request can fetch

---

## 📖 Origin

The name **Arachne** comes from Greek mythology — a mortal weaver so skilled she challenged the goddess Athena.

---

## License

Proprietary — see [LICENSE](LICENSE). Commercial use requires a paid license.
Contact: praveensonesha@gmail.com

