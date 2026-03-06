# Worker HTTP

Temporal activity worker for HTTP-based crawling.

Listens on the `scrape-http` task queue and executes the `ScrapeWorkflow`:
URL fetch → MinIO storage → Redpanda event → CSS/XPath extraction → PostgreSQL update.

Currently uses `httpx` for straightforward fetching. Will upgrade to `curl_cffi` with TLS/JA4+ fingerprint spoofing for anti-detection.
