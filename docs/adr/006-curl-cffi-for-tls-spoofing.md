# ADR-006: curl_cffi for TLS Fingerprint Spoofing

## Status
Accepted

## Date
2026-03-07

## Context
Phase 1 used plain `httpx` for HTTP fetching. While functional, `httpx` produces a TLS ClientHello fingerprint that is trivially identifiable as a Python HTTP client — not a real browser. Modern anti-bot systems (Cloudflare, Akamai, DataDome) inspect TLS fingerprints (JA3/JA4) as the *first* detection layer before any JavaScript fingerprinting occurs.

We need an HTTP client that produces browser-identical TLS handshakes while maintaining Python async compatibility.

## Considered Options

### Option 1: `curl_cffi` (Chosen)
- Uses libcurl-impersonate fork to replicate exact browser TLS ClientHello (JA4), HTTP/2 SETTINGS frames, and header ordering
- Named `impersonate` profiles: `chrome131`, `firefox133`, `safari18_0`, `edge131`
- Supports HTTP/3 over QUIC
- Async support via `AsyncSession`
- All three research agents independently recommended curl_cffi as the #1 choice

### Option 2: `tls-client` (Python)
- Go-based TLS client with Python bindings
- Good fingerprint support but less mature async support
- Smaller community, fewer impersonate profiles

### Option 3: Custom `httpx` with `ssl` context manipulation
- Possible to modify cipher suites via Python's `ssl` module
- Cannot replicate HTTP/2 SETTINGS frames or header ordering
- JA4H fingerprint would still leak Python identity

### Option 4: `requests` + `urllib3` patches
- Legacy approach, fundamentally cannot spoof modern JA4+ fingerprints
- No HTTP/2 support without significant effort

## Decision
Use `curl_cffi` as the primary HTTP client in `packages/anti-detection`, wrapped by `StealthHttpClient`. The client uses browser profile rotation with per-session consistency — profiles are randomized across sessions but locked within a session (same domain = same browser identity).

The `httpx` dependency in `worker-http` is replaced by `arachne-stealth`, which provides `StealthHttpClient`. The Temporal activity interface (`fetch_url`) is unchanged — only the underlying HTTP implementation changes.

## Consequences

### Positive
- HTTP requests now produce browser-identical JA4/JA4H fingerprints
- Sites that returned 403 due to TLS mismatch now return 200
- Foundation for the Evasion Router's Tier 0 (fast HTTP with spoofed TLS)
- Profile rotation prevents fingerprint tracking across sessions

### Negative
- Native C dependency (libcurl) — slightly more complex builds
- Smaller ecosystem than `httpx` (fewer middleware, interceptors)
- Profile list needs updating as new browser versions release

### Neutral
- Performance is comparable to `httpx` for typical scraping workloads
- The `StealthHttpClient` abstraction makes it easy to swap clients in the future
