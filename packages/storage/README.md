# Storage

MinIO client wrapper implementing the Claim-Check pattern.

Large payloads (raw HTML, screenshots, extracted data) are stored in MinIO. Only object references (`minio://bucket/path`) flow through Redpanda messages and database records.

## Usage

```python
from arachne_storage import ArachneStorage, Bucket

storage = ArachneStorage()
ref = storage.store_raw_html(job_id="abc-123", html="<html>...")
html = storage.retrieve_text(ref)
```
