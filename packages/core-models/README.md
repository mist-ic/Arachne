# core-models

Shared Pydantic models used across every Arachne service.

This is the **contract layer** — the single source of truth for what data looks like as it flows through the system. If each service defined its own models, schema drift between services would be inevitable.

## Usage

```python
from arachne_models.jobs import Job, JobCreate, JobStatus
from arachne_models.crawl import CrawlRequest, CrawlResult
from arachne_models.events import CrawlRequestEvent, CrawlResultEvent
```

**Phase 1** — Built in Step 2.
