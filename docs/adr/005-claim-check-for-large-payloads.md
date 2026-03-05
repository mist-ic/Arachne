# ADR-005: Claim-Check Pattern for Large Payloads

## Status
Accepted

## Context

Raw HTML responses can be 1-10MB+. Passing these inline through Redpanda messages and database columns creates:
- **Message broker limits**: Redpanda/Kafka has a default 1MB message limit. Even raised to 10MB, large messages degrade broker performance.
- **Database bloat**: Storing multi-MB HTML in PostgreSQL JSONB columns causes table bloat, slow queries, and expensive backups.
- **Memory pressure**: Temporal serializes activity inputs/outputs. 10MB HTML strings in workflow history = OOM risk.
- **Pipeline coupling**: Every service in the pipeline would need to transfer the full payload, even if it only needs metadata.

### Alternatives Considered

| Approach | Verdict | Why |
|---|---|---|
| **Inline in messages** | Rejected | Hits broker limits, wastes bandwidth for consumers that don't need the content |
| **Database LOB columns** | Rejected | Bloats tables, backups, and replication |
| **Shared filesystem** | Rejected | Doesn't scale, no metadata, no lifecycle management |

## Decision

Use the **Claim-Check pattern** with MinIO as the external store.

Flow:
1. Worker fetches 5MB of HTML
2. Worker uploads to MinIO: `minio://arachne-raw-html/raw/{job_id}/{ts}.html`
3. Worker puts **only the reference string** in the Redpanda message and PostgreSQL row
4. Any downstream service that needs the HTML retrieves it from MinIO using the reference
5. Extraction results follow the same pattern: `minio://arachne-results/results/{job_id}/{ts}.json`

Reference format: `minio://{bucket}/{path}` — parseable, grep-friendly, and self-documenting.

## Consequences

### Positive
- Redpanda messages stay < 1KB (just metadata + references)
- PostgreSQL rows stay lean (just references, not blobs)
- Temporal workflow history stays small (references, not payloads)
- Services only download large payloads when they actually need them
- MinIO provides lifecycle policies for automatic cleanup
- S3-compatible: can swap MinIO for AWS S3 in production

### Negative
- Extra network hop to retrieve content from MinIO
- Need to handle MinIO connectivity errors in consumers
- Content and metadata can get out of sync if MinIO object is deleted but reference remains

### Mitigations
- MinIO is on the same Docker network (sub-ms latency)
- Storage client has retry logic built in
- Lifecycle policies prevent orphaned references
