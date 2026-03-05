#!/usr/bin/env python3
"""
Arachne E2E Demo — Full pipeline demonstration.

Submits a scrape job through the API gateway, polls for completion,
and displays the extracted data. Demonstrates the complete pipeline:

    API → PostgreSQL → Temporal → HTTP fetch → MinIO → Redpanda → Extraction → PostgreSQL

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d

Usage:
    python examples/demo_e2e.py
    python examples/demo_e2e.py --url https://example.com
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

API_BASE = "http://localhost:8000/api/v1"

# Books to Scrape — a safe, legal scraping sandbox by Scraping Hub
DEFAULT_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
DEFAULT_SCHEMA = {
    "fields": {
        "title": {"selector": "h1", "type": "text"},
        "price": {"selector": ".price_color", "type": "text", "transform": "strip_currency"},
        "stock": {"selector": ".instock.availability", "type": "text", "transform": "strip_whitespace"},
        "description": {"selector": "#product_description + p", "type": "text"},
        "upc": {"selector": "//tr[th='UPC']/td", "type": "text"},
        "product_type": {"selector": "//tr[th='Product Type']/td", "type": "text"},
    }
}


def api_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make an HTTP request to the API gateway."""
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description="Arachne E2E Demo")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL to scrape")
    parser.add_argument("--timeout", type=int, default=60, help="Max wait time in seconds")
    args = parser.parse_args()

    print("=" * 70)
    print("  ARACHNE — End-to-End Demo")
    print("=" * 70)
    print()

    # Check API health
    print("[1/5] Checking API health...")
    try:
        health = api_request("GET", "/health")
        print(f"  ✓ API is {health['status']}")
    except URLError as e:
        print(f"  ✗ API unreachable: {e}")
        print("  Run: docker compose -f infra/docker-compose.yml up -d")
        sys.exit(1)

    # Submit job
    print(f"\n[2/5] Submitting scrape job...")
    print(f"  URL: {args.url}")
    print(f"  Schema: {len(DEFAULT_SCHEMA['fields'])} fields")

    result = api_request("POST", "/jobs", {
        "url": args.url,
        "priority": "high",
        "max_retries": 3,
        "extraction_schema": DEFAULT_SCHEMA,
    })

    job_id = result["id"]
    workflow_id = result["workflow_id"]
    print(f"  ✓ Job created: {job_id}")
    print(f"  ✓ Workflow: {workflow_id}")
    print(f"  ✓ Track in Temporal UI: http://localhost:8088/namespaces/default/workflows/{workflow_id}")

    # Poll for completion
    print(f"\n[3/5] Waiting for pipeline completion...")
    start = time.monotonic()
    while time.monotonic() - start < args.timeout:
        job = api_request("GET", f"/jobs/{job_id}")
        status = job["status"]
        elapsed = time.monotonic() - start

        if status in ("completed", "failed", "cancelled"):
            break

        print(f"  ... {status} ({elapsed:.1f}s)")
        time.sleep(2)
    else:
        print(f"  ✗ Timeout after {args.timeout}s")
        sys.exit(1)

    print(f"\n[4/5] Job {status} in {elapsed:.1f}s")

    if status == "completed":
        print(f"  ✓ Raw HTML: {job.get('raw_html_ref', 'N/A')}")
        print(f"  ✓ Result:   {job.get('result_ref', 'N/A')}")
    else:
        print(f"  ✗ Error: {job.get('error_message', 'Unknown')}")

    # Show crawl attempts
    print(f"\n[5/5] Crawl attempt history:")
    attempts = api_request("GET", f"/jobs/{job_id}/attempts")
    for attempt in attempts:
        code = attempt.get("status_code", "N/A")
        ms = attempt.get("elapsed_ms", "N/A")
        err = attempt.get("error", "")
        symbol = "✓" if code and 200 <= code < 400 else "✗"
        print(f"  {symbol} Attempt #{attempt['attempt_number']}: HTTP {code} in {ms}ms{f' — {err}' if err else ''}")

    print()
    print("=" * 70)
    print("  Pipeline: API → PostgreSQL → Temporal → httpx → MinIO")
    print("            → Redpanda → lxml extraction → PostgreSQL + MinIO")
    print("=" * 70)

    # List all jobs
    print(f"\n  Dashboard: http://localhost:8000/docs")
    print(f"  Temporal:  http://localhost:8088")
    print(f"  Redpanda:  http://localhost:8080")
    print(f"  MinIO:     http://localhost:9001 (arachne / arachne123)")
    print()


if __name__ == "__main__":
    main()
