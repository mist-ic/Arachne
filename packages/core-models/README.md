# core-models

Shared Pydantic models used across every Arachne service.

This is the **contract layer** — the single source of truth for what data looks like as it flows through the system. If each service defined its own models, schema drift between services would be inevitable.

## Installation

```bash
# From any app directory in the monorepo
uv pip install -e ../../packages/core-models
```

## Usage

```python
from arachne_models.jobs import Job, JobCreate, JobStatus, JobPriority
from arachne_models.crawl import CrawlRequest, CrawlResult
from arachne_models.events import CrawlRequestEvent, CrawlResultEvent
from arachne_models.extraction import ExtractionSchema, FieldConfig, ExtractionResult

# Or import directly from the package root
from arachne_models import Job, CrawlRequest, ExtractionSchema
```

## Models

| Module | Models | Purpose |
|---|---|---|
| `jobs.py` | `JobStatus`, `JobPriority`, `JobCreate`, `Job` | Job lifecycle from submission to completion |
| `crawl.py` | `CrawlRequest`, `CrawlResult` | Crawl task dispatch and results |
| `events.py` | `CrawlRequestEvent`, `CrawlResultEvent`, `ExtractionRequestEvent`, `ExtractionResultEvent` | Redpanda topic schemas |
| `extraction.py` | `FieldConfig`, `ExtractionSchema`, `ExtractionResult` | CSS/XPath extraction config and output |
