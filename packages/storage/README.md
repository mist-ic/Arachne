# storage

MinIO (S3-compatible) client wrapper implementing the Claim-Check pattern.

Large payloads (raw HTML, screenshots, HAR files) are stored in MinIO — only the object reference flows through Redpanda messages.

**Phase 1** — Built in Step 4.
