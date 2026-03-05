# worker-http

Temporal worker that fetches web pages via HTTP.

Phase 1 uses `httpx` for straightforward fetching. Phase 2 upgrades to `curl_cffi` with TLS/JA4+ fingerprint spoofing.

**Phase 1** — Built in Steps 5, 8.
