# Architecture

> C4 Model for the Arachne Web Intelligence Platform

## Context Diagram (Level 1)

```mermaid
C4Context
    title Arachne — System Context
    
    Person(user, "Developer / Data Engineer", "Submits scraping jobs, views results")
    System(arachne, "Arachne Platform", "Web intelligence platform with anti-detection, AI extraction, and autonomous monitoring")
    System_Ext(targets, "Target Websites", "E-commerce, SaaS, news sites")
    System_Ext(llm_apis, "LLM APIs", "Gemini, GPT-5, Claude-4")
    System_Ext(captcha, "CAPTCHA Services", "2Captcha, CapSolver")
    System_Ext(proxies, "Proxy Providers", "Rotating residential/datacenter proxies")
    
    Rel(user, arachne, "Submits jobs, views dashboard")
    Rel(arachne, targets, "Crawls with anti-detection")
    Rel(arachne, llm_apis, "Structured extraction")
    Rel(arachne, captcha, "Solves CAPTCHAs")
    Rel(arachne, proxies, "Routes through proxies")
```

## Container Diagram (Level 2)

```mermaid
C4Container
    title Arachne — Container Diagram

    Person(user, "Developer")

    System_Boundary(arachne, "Arachne Platform") {
        Container(api, "API Gateway", "FastAPI", "REST API for job management")
        Container(dashboard, "Dashboard", "React + Vite", "Real-time operations UI")
        Container(worker_http, "Worker HTTP", "Python + Temporal", "curl_cffi crawling")
        Container(worker_stealth, "Worker Stealth", "Python + Temporal", "Browser-based crawling")
        Container(extraction, "Extraction Engine", "Python + Temporal", "LLM + Vision extraction")
        
        ContainerDb(postgres, "PostgreSQL", "Relational DB", "Jobs, schemas, results")
        ContainerQueue(redpanda, "Redpanda", "Kafka API", "Event streaming")
        ContainerDb(minio, "MinIO", "Object Storage", "Screenshots, HTML snapshots")
        Container(temporal, "Temporal", "Workflow Engine", "Orchestration")
        Container(ollama, "Ollama", "Local LLM", "Qwen3-VL, embedding models")
        
        Container(clickhouse, "ClickHouse", "Columnar DB", "Telemetry storage")
        Container(otel, "OTel Collector", "OTLP", "Telemetry pipeline")
        Container(hyperdx, "HyperDX", "Observability UI", "Logs, traces, metrics")
    }

    Rel(user, api, "REST API", "HTTP/JSON")
    Rel(user, dashboard, "Views", "HTTPS")
    Rel(api, temporal, "Dispatches workflows")
    Rel(temporal, worker_http, "Schedules activities")
    Rel(temporal, worker_stealth, "Schedules activities")
    Rel(temporal, extraction, "Schedules activities")
    Rel(worker_http, redpanda, "Publishes crawl results")
    Rel(worker_stealth, redpanda, "Publishes crawl results")
    Rel(extraction, redpanda, "Consumes crawl results")
    Rel(extraction, ollama, "Local vision/LLM")
    Rel(extraction, postgres, "Stores results")
    Rel(extraction, minio, "Stores screenshots")
    Rel(otel, clickhouse, "Exports telemetry")
    Rel(hyperdx, clickhouse, "Queries telemetry")
```

## Component Diagram (Level 3) — Extraction Engine

```mermaid
C4Component
    title Extraction Engine — Components

    Container_Boundary(extraction, "Extraction Engine") {
        Component(preprocessor, "Preprocessor", "Python", "DOM pruning + HTML→Markdown")
        Component(chunker, "Chunker", "Python", "Context-aware markdown splitting")
        Component(llm_extractor, "LLM Extractor", "instructor + LiteLLM", "Schema-bound extraction")
        Component(model_router, "Model Router", "Python", "Cost/accuracy routing")
        Component(schema_discovery, "Schema Discovery", "Python", "Auto-schema from raw pages")
        Component(vision_extractor, "Vision Extractor", "Python", "Screenshot → VLM → data")
        Component(result_merger, "Result Merger", "Python", "HTML + Vision merge")
        Component(vision_pipeline, "Vision Pipeline", "SAM3 + RF-DETR", "CV segmentation + detection")
        Component(drift_detector, "Drift Detector", "Python", "4-signal drift monitoring")
        Component(schema_repairer, "Schema Repairer", "LLM", "Auto-repair broken schemas")
        Component(change_detector, "Change Detector", "Python", "Multi-signal change aggregation")
    }

    Rel(preprocessor, chunker, "Markdown chunks")
    Rel(chunker, llm_extractor, "Chunks + schema")
    Rel(model_router, llm_extractor, "Selects model")
    Rel(llm_extractor, vision_extractor, "Fallback when confidence < 0.5")
    Rel(vision_extractor, result_merger, "Vision results")
    Rel(vision_pipeline, vision_extractor, "SAM/DETR crops")
    Rel(drift_detector, schema_repairer, "Triggers repair")
    Rel(llm_extractor, drift_detector, "Reports metrics")
```

## Package Structure

```
Arachne/
├── apps/
│   ├── api-gateway/         # FastAPI REST API
│   ├── dashboard/           # React + Vite command center
│   ├── extraction-engine/   # AI extraction Temporal worker
│   ├── worker-http/         # curl_cffi HTTP crawling
│   └── worker-stealth/      # Browser-based crawling
├── packages/
│   ├── extraction/          # Core extraction library
│   │   ├── vision/          # SAM 3 + RF-DETR pipeline
│   │   ├── drift/           # Schema drift detection
│   │   ├── change/          # Change detection engine
│   │   └── captcha/         # CAPTCHA solving
│   ├── observability/       # OTel, metrics, logging, DuckDB
│   ├── stealth/             # Anti-detection evasion engine
│   └── storage/             # MinIO + PostgreSQL clients
├── infra/
│   ├── docker-compose.yml   # Full stack: 12+ services
│   └── otel-collector-config.yaml
├── benchmarks/              # Performance comparison scripts
└── docs/
    └── adr/                 # Architectural Decision Records
```

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| HTTP Crawling | curl_cffi | JA4 fingerprint spoofing, HTTP/2 |
| Browser Crawling | Camoufox, Pydoll | Anti-fingerprinting stealth |
| Evasion Router | Custom | Adaptive strategy selection |
| Extraction | instructor + LiteLLM | Schema-bound Pydantic output |
| Vision | SAM 3, RF-DETR, Qwen3-VL | Multi-model CV pipeline |
| Orchestration | Temporal | Deterministic workflow engine |
| Messaging | Redpanda | Kafka API, no JVM |
| Storage | PostgreSQL + MinIO | Structured + object storage |
| Observability | ClickHouse + HyperDX | ClickStack telemetry |
| Dashboard | React + Vite | Real-time operations UI |
| Local AI | Ollama | Self-hosted vision models |

## Data Flow

```mermaid
graph LR
    A[Job Submitted] --> B{Evasion Router}
    B -->|Simple| C[curl_cffi Worker]
    B -->|Protected| D[Stealth Browser]
    C --> E[Redpanda]
    D --> E
    E --> F{Extraction Engine}
    F -->|HTML Extraction| G[LLM Extractor]
    F -->|Low Confidence| H[Vision Fallback]
    G --> I[Result Merger]
    H --> I
    I --> J[(PostgreSQL)]
    I --> K[Drift Detector]
    K -->|Drift Found| L[Auto Repairer]
    L --> M[Schema History]
```
