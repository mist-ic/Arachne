<div align="center">

# 🕷️ Arachne

### Autonomous Web Intelligence Platform

*Production-grade web scraping that sees like a human, adapts to site changes,
and heals its own extraction schemas - powered by a distributed pipeline
with full observability from request to result.*

<br>

[![Python 3.13+](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/TypeScript-Dashboard-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](apps/dashboard/)
[![Temporal](https://img.shields.io/badge/Temporal-Durable_Workflows-000000?style=for-the-badge&logo=temporal&logoColor=white)](https://temporal.io)
[![Redpanda](https://img.shields.io/badge/Redpanda-Event_Streaming-E2003E?style=for-the-badge&logo=redpanda&logoColor=white)](https://redpanda.com)
[![ClickHouse](https://img.shields.io/badge/ClickHouse-Analytics-FFCC01?style=for-the-badge&logo=clickhouse&logoColor=black)](https://clickhouse.com)
[![License](https://img.shields.io/badge/License-Proprietary-EF4444?style=for-the-badge)](LICENSE)

<br>

**[Quick Start](#-quick-start)** · **[Architecture](#-architecture)** · **[Key Features](#-key-features)** · **[Benchmarks](#-benchmarks)** · **[Tech Stack](#-tech-stack)** · **[Documentation](#-documentation)**

</div>

---

## What Is Arachne?

**Arachne is an autonomous web intelligence platform** that combines production-grade anti-detection, AI-first structured extraction, and computer vision into a single distributed system. It crawls protected websites by spoofing TLS fingerprints and deploying stealth browsers, extracts structured data using LLMs with schema-bound validation, and monitors target sites for changes - automatically repairing its own extraction schemas when sites redesign. The entire pipeline is observable end-to-end through ClickHouse-backed distributed tracing, with a real-time React dashboard for operational visibility.

**No open-source project occupies the intersection of anti-detection, AI extraction, and distributed architecture.** That's the gap Arachne fills.

---

## The Problem

| Domain | The Status Quo | Arachne's Approach |
|--------|---------------|-------------------|
| **Anti-Detection** | Most scrapers get 403'd by TLS fingerprinting, behavioral ML, and polymorphic JS challenges | JA4+ TLS spoofing via `curl_cffi`, stealth browsers (Camoufox + Pydoll), behavioral simulation, 4-tier adaptive evasion with automatic escalation |
| **AI Extraction** | Tools like Crawl4AI assume you can already *get* the HTML - none handle evasion | LLM schema-bound extraction via `instructor`, multi-model routing, auto-schema discovery, SAM 3 + RF-DETR computer vision pipeline, vision CAPTCHA solving |
| **Self-Healing** | Scrapers break when sites change and require manual intervention | 4-signal schema drift detection, LLM-powered auto-repair, schema version history with rollback |
| **Distributed Scraping** | Production-scale systems exist only as closed-source SaaS ($50-500+/mo) | Open-source pipeline: Redpanda streams, Temporal durable workflows, PostgreSQL + MinIO + ClickHouse |

---

## 🚀 Quick Start

```bash
# Prerequisites: Docker, Docker Compose
# Optional: Gemini API key for AI extraction, GPU for local models

# 1. Clone and configure
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY (optional)

# 2. Start the full distributed system (one command)
docker compose -f infra/docker-compose.yml up -d

# 3. Run database migrations (first time only)
cd packages/core-models && alembic upgrade head && cd ../..

# 4. Wait ~30s for services to spin up, then run the E2E demo
python examples/demo_e2e.py
```

### What Happens

The demo submits a URL through the **API Gateway**, which triggers a **Temporal durable workflow**. The workflow fetches the page via `curl_cffi` (or escalates through stealth tiers if blocked), stores raw HTML in **MinIO** (Claim-Check pattern), streams events through **Redpanda**, runs AI extraction via `instructor` + LLMs with optional vision fallback, and persists structured JSON to **PostgreSQL**. Everything is traced end-to-end through the **OTel Collector** → **ClickHouse** → **HyperDX** observability stack.

### Service Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| **API Gateway** | [localhost:8000/docs](http://localhost:8000/docs) | REST API with Swagger UI |
| **Dashboard** | [localhost:5173](http://localhost:5173) | Real-time operations command center |
| **Temporal UI** | [localhost:8088](http://localhost:8088) | Workflow execution monitoring |
| **HyperDX** | [localhost:8090](http://localhost:8090) | Unified logs, traces, metrics |
| **Redpanda Console** | [localhost:8080](http://localhost:8080) | Event stream inspection |
| **MinIO Console** | [localhost:9001](http://localhost:9001) | Object storage browser (`arachne` / `arachne123`) |
| **ClickHouse** | [localhost:8123](http://localhost:8123) | Telemetry analytics (HTTP interface) |
| **Ollama** | [localhost:11434](http://localhost:11434) | Local LLM inference server |

---

## 🏗️ Architecture

> Full C4 diagrams with Mermaid visualizations available in [ARCHITECTURE.md](ARCHITECTURE.md)

```
                                    ┌────────────────────────────────────────────────────────┐
                                    │                    CONTROL PLANE                       │
                                    │                                                        │
   ┌──────────┐    REST/WS          │  ┌──────────────┐        ┌──────────────────────┐      │
   │  Client  │───────────────────▶│  │  API Gateway  │──────▶│  PostgreSQL          │      │
   └──────────┘                     │  │  (FastAPI)    │       │  (jobs, schemas,     │      │
                                    │  └───────┬───────┘       │   results, attempts) │      │
   ┌──────────┐                     │          │               └──────────────────────┘      │
   │ Dashboard│◀───WebSocket──────│──────────┤                                              │
   │ (React)  │                    │          │                                              │
   └──────────┘                    └──────────┼──────────────────────────────────────────────┘
                                               │ Start workflow
                                               ▼
                                    ┌──────────────────┐
                                    │     Temporal     │
                                    │  (Orchestration) │
                                    └────┬────────┬────┘
                                         │        │
                        ┌────────────────┘        └────────────────┐
                        ▼                                          ▼
          ┌──────────────────────┐                   ┌────────────────────┐
          │    worker-http       │                   │   worker-stealth   │
          │  ┌────────────────┐  │                   │  ┌────────────────┐│
          │  │  curl_cffi     │  │  escalate on 403  │  │  Camoufox      ││
          │  │  (Tier 1-2)    │──┼─────────────────▶│  │  Pydoll        ││
          │  └────────────────┘  │                   │  │  (Tier 3-4)    ││
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
                      │              │  │ Vision Fallback   │ │
                      │              │  │ SAM3+DETR Pipeline│ │
                      │              │  │ Schema Discovery │  │
                      │              │  │ Drift Detection  │  │
                      │              │  │ CAPTCHA Solver   │  │
                      │              │  └──────────────────┘  │
                      │              └───────────┬────────────┘
                      │                          │
                      ▼                          ▼
              ┌──────────────┐          ┌──────────────┐
              │  Redpanda    │          │   Ollama     │
              │  (events)    │          │  (local LLM) │
              └──────┬───────┘          └──────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
   ┌─────────────┐    ┌──────────────┐
   │ OTel        │    │ ClickHouse   │
   │ Collector   │───▶│ (telemetry) │
   └─────────────┘    └──────┬───────┘
                              │
                     ┌────────▼────────┐
                     │    HyperDX      │
                     │  (observability)│
                     └─────────────────┘
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

---

### 🧠 AI Extraction Engine

```
Raw HTML → DOM Pruning → HTML-to-Markdown (5-10x token reduction)
                                    ↓
                          Context-aware Chunking
                                    ↓
                          Model Router (cost/accuracy/SLO)
                          ↓           ↓            ↓
                       Local       Fast Cloud    Frontier
                      (Ollama)     (Flash)       (Pro)
                          ↓
                   instructor + Pydantic (schema-bound extraction)
                          ↓
                   Confidence < threshold?
                   ↓ No                    ↓ Yes
             ExtractionOutput     Screenshot → Vision Fallback
                                         ↓
                                  Qwen3-VL / GPT-5 Vision
                                         ↓
                                  Result Merger (HTML + Vision)
                                         ↓
                                  ExtractionOutput
```

| Capability | Implementation |
|-----------|---------------|
| **HTML Preprocessing** | Semantic DOM pruning, link-to-citation conversion, BM25 relevance filtering |
| **Schema-Bound Extraction** | `instructor` + `LiteLLM` → validated Pydantic models with anti-hallucination prompts |
| **Multi-Model Routing** | ComplexityEstimator → 3-tier cascade: Local (free) → Fast ($0.10/M) → Frontier ($1.25/M) |
| **Vision Fallback** | When HTML extraction confidence is low, screenshot → VLM → merge with HTML results |
| **SAM 3 + RF-DETR Pipeline** | Three-model CV pipeline: segmentation → detection → per-segment VLM extraction |
| **Auto-Schema Discovery** | LLM analysis + hybrid DOM repeated-subtree detection → dynamic `create_model()` |
| **CAPTCHA Solving** | Local: Qwen3-VL via Ollama (free). External: 2Captcha + CapSolver. Cascading fallback chain |
| **Cost Control** | Per-page cost ceiling, per-domain model history, cost mode selection (minimize/balanced/accuracy) |

---

### 🔄 Schema Drift Detection & Self-Healing

Arachne **automatically detects when target sites change** and repairs its own extraction schemas without human intervention:

| Signal | What It Detects |
|--------|----------------|
| **Validation Failure Rate** | Sudden spike in Pydantic validation failures per domain |
| **Field Completeness** | Previously-reliable fields suddenly missing from extractions |
| **Embedding Similarity** | Semantic content structure changed vs. historical baseline |
| **Schema Divergence** | Auto-discovered schema differs from the active deployed schema |

When drift is detected → LLM proposes updated schema → validates against sample pages → auto-deploys if passing → logs for human review. Full schema version history with rollback support.

---

### 📡 Multi-Signal Change Detection

Goes far beyond hash-based diffing to detect *meaningful* changes:

| Signal | Catches | Ignores |
|--------|---------|---------|
| **DOM Differencing** | Template changes, restructured layout | Dynamic attributes, CSRF tokens |
| **Embedding Similarity** | Content meaning changes (new products, updated descriptions) | Phrasing tweaks |
| **Visual Diff (pHash/SSIM)** | Major redesigns visible to humans | Invisible HTML-only changes |
| **Entity Comparison** | Price changes, new/removed data fields | Boilerplate changes |

Aggregated into a 0–1 change score: `<0.1` no change → `0.1–0.5` content update → `0.5–0.8` layout change → `>0.8` major redesign.

---

### 📊 Real-Time Dashboard

React + Vite command center with an **industrial control aesthetic** - live pipeline monitoring, extraction analytics, and anti-bot evasion visualization.

| Page | What It Shows |
|------|--------------|
| **Live Feed** | Real-time scrolling pipeline activity with auto-updating stat cards |
| **Extraction Stats** | Model performance comparison, throughput bars, per-domain accuracy with health indicators |
| **Evasion Map** | Anti-bot vendor encounter cards, evasion success rates, strategy effectiveness |

---

### 🔭 ClickStack Observability

Full **ClickHouse + HyperDX + OTel Collector** stack replacing traditional Prometheus/Grafana:

- **Unified backend**: Logs, metrics, AND traces stored in ClickHouse (one db, not four systems)
- **Correlated views**: Click a trace → see related logs → see metrics in HyperDX
- **Scraping-specific metrics**: Anti-bot encounter rate, proxy health, LLM token cost, CAPTCHA solve rate, Redpanda consumer lag, schema drift events
- **DuckDB analytics**: Ad-hoc SQL queries over extraction results for benchmark reports

---

## 📈 Benchmarks

> Full methodology and data in [BENCHMARKS.md](BENCHMARKS.md)

### Extraction Accuracy by Model

| Model | Avg Confidence | Cost/1K Extractions | Avg Latency |
|-------|---------------|--------------------:|-------------|
| gemini-2.5-flash | **0.94** | $0.15 | 1.2s |
| gpt-5 | **0.97** | $4.20 | 2.8s |
| qwen3-vl (local) | 0.82 | **$0.00** | 3.5s |
| claude-4-sonnet | **0.95** | $1.80 | 2.1s |

### Vision Pipeline: Full CV vs Direct VLM

| Method | Completeness | Latency |
|--------|-------------|---------|
| SAM 3 + RF-DETR Pipeline | **93%** | 3.2s |
| Direct VLM (full screenshot) | 73% | 2.1s |

The CV pipeline extracts **27% more fields** at a 52% latency premium.

### Anti-Detection Evasion Rates

| Vendor | Evasion Rate | Strategy |
|--------|-------------|----------|
| Cloudflare | **93%** | TLS Spoof + Camoufox |
| PerimeterX | **94%** | TLS Spoof + Fingerprint Rotation |
| Akamai | **85%** | Pydoll + Cookie Replay |
| DataDome | **87%** | Browser Stealth + Proxy Rotation |

---

## 🔧 Tech Stack

| Layer | Technology | Why This |
|-------|-----------|----------|
| **HTTP Client** | `curl_cffi` | JA4+ TLS fingerprint spoofing, HTTP/2 |
| **Browsers** | Camoufox, Pydoll | Anti-fingerprint Firefox fork + CDP Chrome automation |
| **LLM Framework** | `instructor` + `LiteLLM` | Schema-bound Pydantic extraction, provider-agnostic |
| **Computer Vision** | SAM 3, RF-DETR, Qwen3-VL | Multi-model CV pipeline for vision extraction |
| **Message Broker** | Redpanda | Kafka API compatibility, zero-JVM, sub-ms latency |
| **Orchestration** | Temporal | Durable execution, automatic retries, workflow versioning |
| **Database** | PostgreSQL 16 | JSONB schemas, Alembic migrations |
| **Object Storage** | MinIO | S3-compatible, self-hosted, Claim-Check pattern |
| **Telemetry** | ClickHouse + HyperDX | ClickStack: unified logs/metrics/traces |
| **Telemetry Pipeline** | OTel Collector | OTLP receivers → ClickHouse exporters |
| **Analytics** | DuckDB | In-process SQL over extraction results |
| **Local AI** | Ollama | GPU-accelerated Qwen3-VL, embedding models |
| **Dashboard** | React + Vite + TypeScript | Real-time operations UI |
| **Containerization** | Docker Compose | One-command 12+ service stack |
| **Monorepo** | Moonrepo | Cross-language task orchestration |
| **CI** | GitHub Actions | 4-job parallel: lint, test, build, docker validate |

---

## 📁 Project Structure

```
Arachne/
├── apps/
│   ├── api-gateway/              # FastAPI REST API + job management
│   ├── worker-http/              # Temporal worker: curl_cffi crawling
│   ├── worker-stealth/           # Temporal worker: stealth browser sessions
│   ├── extraction-engine/        # Temporal worker: AI extraction + vision + drift
│   └── dashboard/                # React + Vite real-time command center
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
│   ├── extraction/               # 🧠 AI extraction engine (16+ modules)
│   │   ├── preprocessor.py       #     DOM pruning, HTML→Markdown, BM25
│   │   ├── chunker.py            #     Context-aware chunking
│   │   ├── llm_extractor.py      #     instructor + LiteLLM extraction
│   │   ├── model_router.py       #     Multi-model routing + cascade
│   │   ├── schema_discovery.py   #     Auto-schema via LLM/DOM analysis
│   │   ├── vision_extractor.py   #     Screenshot → VLM extraction
│   │   ├── result_merger.py      #     HTML + Vision field-by-field merge
│   │   ├── vision/               #     SAM 3 + RF-DETR CV pipeline
│   │   ├── drift/                #     Schema drift detection + auto-repair
│   │   ├── change/               #     Multi-signal change detection
│   │   └── captcha/              #     CAPTCHA detection + solving
│   │
│   ├── core-models/              # Pydantic schemas + SQLAlchemy + Alembic
│   ├── messaging/                # Redpanda producer/consumer
│   ├── storage/                  # MinIO client wrapper
│   └── observability/            # OTel, metrics, logging, DuckDB, hardening
│
├── infra/
│   ├── docker-compose.yml        # 12+ services: full distributed stack
│   └── otel-collector-config.yaml # OTLP → ClickHouse pipeline config
│
├── .devcontainer/                # One-click dev environment (VS Code / Codespaces)
├── .github/workflows/ci.yml     # 4-job parallel CI pipeline
├── docs/adr/                     # 8 Architecture Decision Records
├── benchmarks/                   # Performance comparison scripts
├── ARCHITECTURE.md               # C4 model with Mermaid diagrams
└── BENCHMARKS.md                 # Empirical performance data
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | C4 model: System Context, Container, Component, Data Flow diagrams |
| [BENCHMARKS.md](BENCHMARKS.md) | Model accuracy, vision pipeline, evasion rates, cost analysis |

### Architecture Decision Records

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

---

## 🧪 Development

### DevContainer (Recommended)

Open in VS Code → **"Reopen in Container"** - gets you Python 3.13, Node 22, Bun, Docker-in-Docker, and all extensions pre-configured. Also works with GitHub Codespaces.

### Manual Setup

```bash
# Start everything
docker compose -f infra/docker-compose.yml up -d

# Check service health
docker compose -f infra/docker-compose.yml ps

# View logs
docker compose -f infra/docker-compose.yml logs -f extraction-engine

# Run tests
pytest packages/ apps/ --cov=packages -v

# Format + lint
ruff check packages/ apps/
ruff format packages/ apps/
```

### Environment Variables

Copy `.env.example` and configure:

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key (for AI extraction) |
| `ARACHNE_COST_MODE` | Model routing: `minimize` / `balanced` / `accuracy` |
| `ARACHNE_DEFAULT_MODEL` | Default LiteLLM model (e.g., `gemini/gemini-2.5-flash`) |

---

## 🏛️ Design Philosophy

- **Best-in-class everything** - We pick whatever is genuinely the best tool regardless of familiarity or popularity
- **No half-measures** - Complete implementations of each system, not proof-of-concept stubs
- **Self-healing intelligence** - Drift detection and auto-repair mean the system adapts without human intervention
- **Full observability** - Every request traced across the entire distributed pipeline via ClickStack
- **Cost-aware AI** - Multi-model routing ensures bulk pages cost $0 (local) while complex pages get frontier accuracy
- **Adaptive evasion** - Start cheap, escalate automatically. Don't waste a stealth browser on a site that HTTP can fetch

---

## 📖 Origin

The name **Arachne** comes from Greek mythology - a mortal weaver so skilled she challenged the goddess Athena.

---

## License

Proprietary - see [LICENSE](LICENSE). Commercial use requires a paid license.
Contact: praveensonesha@gmail.com
