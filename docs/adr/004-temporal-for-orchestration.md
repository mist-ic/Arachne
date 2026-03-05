# ADR-004: Temporal for Workflow Orchestration

## Status
Accepted

## Context

Arachne needs a way to orchestrate multi-step scrape pipelines reliably:
URL fetch → HTML storage → event publishing → extraction → status update.

Each step can fail independently (network timeouts, storage errors, broker downtime). The orchestration layer must handle retries, timeouts, failure recovery, and state persistence without losing work or creating duplicates.

### Alternatives Considered

| Tool | Verdict | Why |
|---|---|---|
| **Celery** | Rejected | Task queue model is a subset of what Temporal provides. No durable state, no workflow history, limited retry control. "Celery is redundant when using Temporal + Redpanda." |
| **Airflow** | Rejected | Data pipeline scheduler, not a general workflow engine. DAG-centric, not suited for event-driven scraping with dynamic retry logic |
| **Custom state machine** | Rejected | Reinventing durable execution is a multi-month effort. Error-prone, no UI, no built-in retries |
| **Redpanda-only (choreography)** | Rejected | Works for simple flows, but multi-step pipelines with conditional branching, retries, and compensation become tangled. Orchestration > choreography for this use case |

## Decision

Use **Temporal** for workflow orchestration.

Key factors:
- **Durable execution**: If a worker crashes mid-activity, Temporal resumes on another worker at the exact line of code. Zero lost work.
- **Activity-level retries**: Each activity has its own retry policy with typed non-retryable errors (e.g. 404 never retries, 429 always does)
- **Workflow history**: Full audit trail of every activity execution, timing, and error — visible in Temporal UI
- **Horizontal scaling**: Multiple workers can process the same task queue — Temporal distributes work automatically
- **Timeouts at every level**: Per-activity, per-workflow, schedule-to-start, start-to-close — complete control
- **Compensation/cleanup**: On failure, the workflow can run cleanup activities (publish failure events, update status)

## Consequences

### Positive
- Complete failure recovery with zero custom retry logic
- Full workflow visibility in Temporal UI (workflow history, pending activities, errors)
- Clean separation of orchestration (workflow) from work (activities)
- Horizontal scaling is trivial (run more workers)
- Impressive portfolio signal — demonstrates understanding of durable execution patterns

### Negative
- Additional infrastructure dependency (Temporal server + PostgreSQL backend)
- Learning curve for Temporal SDK concepts (workflow sandbox, activity registration)
- Temporal SDK has specific serialization requirements (dataclasses over Pydantic in workflows)

### Mitigations
- Temporal's auto-setup Docker image makes local development trivial
- Separate PostgreSQL instance isolates Temporal state from application data
- Worker code follows standard patterns that are well-documented
