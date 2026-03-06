"""
Tests for API discovery from network requests.
"""

import pytest

from arachne_stealth.api_discovery import (
    APIDiscoveryReport,
    DiscoveredAPI,
    analyze_network_requests,
)


class TestAnalyzeNetworkRequests:
    """Tests for network request analysis."""

    def test_detects_json_endpoint(self):
        """Should identify JSON API endpoints."""
        requests = [
            {"url": "https://api.example.com/v2/products", "status": 200,
             "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")

        assert report.total_apis_found >= 1
        assert len(report.json_endpoints) >= 1

    def test_detects_graphql_endpoint(self):
        """Should identify GraphQL endpoints."""
        requests = [
            {"url": "https://example.com/graphql", "status": 200,
             "method": "POST", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")

        assert len(report.graphql_endpoints) >= 1

    def test_ignores_static_resources(self):
        """Should filter out CSS, JS, images, etc."""
        requests = [
            {"url": "https://example.com/style.css", "status": 200,
             "method": "GET", "mime_type": "text/css", "headers": {}},
            {"url": "https://example.com/logo.png", "status": 200,
             "method": "GET", "mime_type": "image/png", "headers": {}},
            {"url": "https://example.com/app.js", "status": 200,
             "method": "GET", "mime_type": "application/javascript", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        assert report.total_apis_found == 0

    def test_ignores_analytics(self):
        """Should filter out analytics trackers."""
        requests = [
            {"url": "https://www.google-analytics.com/collect", "status": 200,
             "method": "GET", "mime_type": "text/javascript", "headers": {}},
            {"url": "https://www.googletagmanager.com/gtm.js", "status": 200,
             "method": "GET", "mime_type": "application/javascript", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        assert report.total_apis_found == 0

    def test_ignores_failed_requests(self):
        """Should ignore non-2xx responses."""
        requests = [
            {"url": "https://api.example.com/v2/secret", "status": 401,
             "method": "GET", "mime_type": "application/json", "headers": {}},
            {"url": "https://api.example.com/v2/error", "status": 500,
             "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        assert report.total_apis_found == 0

    def test_detects_pagination_offset(self):
        """Should detect offset-based pagination."""
        requests = [
            {"url": "https://api.example.com/products?offset=0&limit=20",
             "status": 200, "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")

        assert report.total_apis_found >= 1
        api = report.json_endpoints[0]
        assert api.has_pagination is True
        assert api.pagination_type == "offset"

    def test_detects_pagination_cursor(self):
        """Should detect cursor-based pagination."""
        requests = [
            {"url": "https://api.example.com/feed?cursor=abc123",
             "status": 200, "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        api = report.json_endpoints[0]
        assert api.has_pagination is True
        assert api.pagination_type == "cursor"

    def test_detects_pagination_page(self):
        """Should detect page-based pagination."""
        requests = [
            {"url": "https://api.example.com/items?page=2",
             "status": 200, "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        api = report.json_endpoints[0]
        assert api.has_pagination is True
        assert api.pagination_type == "page"

    def test_empty_requests_returns_empty_report(self):
        """Empty request list should produce empty report."""
        report = analyze_network_requests([], domain="example.com")
        assert report.total_apis_found == 0
        assert report.total_requests_captured == 0

    def test_api_endpoint_path(self):
        """DiscoveredAPI should extract the URL path."""
        api = DiscoveredAPI(url="https://api.example.com/v2/products?page=1")
        assert api.endpoint_path == "/v2/products"

    def test_mixed_requests(self):
        """Should correctly categorize mixed request types."""
        requests = [
            # Should be found: JSON API
            {"url": "https://api.example.com/v2/data", "status": 200,
             "method": "GET", "mime_type": "application/json", "headers": {}},
            # Should be ignored: static
            {"url": "https://example.com/style.css", "status": 200,
             "method": "GET", "mime_type": "text/css", "headers": {}},
            # Should be found: GraphQL
            {"url": "https://example.com/graphql", "status": 200,
             "method": "POST", "mime_type": "application/json", "headers": {}},
            # Should be ignored: analytics
            {"url": "https://www.google-analytics.com/collect", "status": 200,
             "method": "GET", "mime_type": "application/json", "headers": {}},
        ]
        report = analyze_network_requests(requests, domain="example.com")
        assert report.total_requests_captured == 4
        assert len(report.json_endpoints) >= 1
        assert len(report.graphql_endpoints) >= 1
