"""
Tests for anti-bot vendor detection.
"""

import pytest

from arachne_stealth.vendor_detect import VendorDetection, detect_vendor


class TestVendorDetection:
    """Tests for vendor detection from response signals."""

    def test_cloudflare_basic_by_header(self):
        """Should detect basic Cloudflare from cf-ray header + server header."""
        result = detect_vendor(
            headers={"cf-ray": "abc123-IAD", "server": "cloudflare"},
            domain="test.com",
        )
        assert result.vendor.startswith("cloudflare")
        assert result.confidence > 0
        assert len(result.signals) > 0

    def test_cloudflare_turnstile_by_body(self):
        """Should detect Cloudflare Turnstile from HTML body pattern."""
        html = '<div class="cf-turnstile" data-sitekey="abc"></div>'
        result = detect_vendor(
            headers={"cf-ray": "abc123-IAD"},
            body=html,
            domain="test.com",
        )
        assert "cloudflare" in result.vendor
        assert result.confidence > 0

    def test_akamai_by_cookie(self):
        """Should detect Akamai from _abck cookie."""
        result = detect_vendor(
            headers={"server": "AkamaiGHost"},
            cookies={"_abck": "abc123", "bm_sz": "xyz"},
            domain="test.com",
        )
        assert result.vendor == "akamai"
        assert result.confidence > 0.3
        assert any("cookie:_abck" in s for s in result.signals)

    def test_datadome_by_header(self):
        """Should detect DataDome from x-datadome header."""
        result = detect_vendor(
            headers={"x-datadome": "1", "server": "DataDome"},
            domain="test.com",
        )
        assert result.vendor == "datadome"
        assert result.confidence > 0

    def test_datadome_by_cookie_and_body(self):
        """Should detect DataDome from cookie + JS reference."""
        result = detect_vendor(
            headers={},
            cookies={"datadome": "abc123"},
            body='<script src="https://js.datadome.co/tags.js"></script>',
            domain="test.com",
        )
        assert result.vendor == "datadome"

    def test_kasada_by_headers(self):
        """Should detect Kasada from x-kpsdk headers."""
        result = detect_vendor(
            headers={"x-kpsdk-ct": "abc", "x-kpsdk-v": "1"},
            domain="test.com",
        )
        assert result.vendor == "kasada"

    def test_perimeterx_by_cookies(self):
        """Should detect PerimeterX from _px cookies."""
        result = detect_vendor(
            headers={},
            cookies={"_pxhd": "abc", "_pxvid": "xyz"},
            domain="test.com",
        )
        assert result.vendor == "perimeterx"

    def test_aws_waf_by_header(self):
        """Should detect AWS WAF."""
        result = detect_vendor(
            headers={"x-amzn-waf-action": "allow"},
            domain="test.com",
        )
        assert result.vendor == "aws_waf"

    def test_recaptcha_by_body(self):
        """Should detect reCAPTCHA from HTML body."""
        html = '<div class="g-recaptcha" data-sitekey="abc"></div>'
        result = detect_vendor(
            headers={},
            body=html,
            domain="test.com",
        )
        assert result.vendor == "recaptcha"

    def test_hcaptcha_by_body(self):
        """Should detect hCaptcha from HTML body."""
        html = '<script src="https://js.hcaptcha.com/1/api.js"></script>'
        result = detect_vendor(
            headers={},
            body=html,
            domain="test.com",
        )
        assert result.vendor == "hcaptcha"

    def test_no_vendor_detected(self):
        """Should return 'none' when no vendor is detected."""
        result = detect_vendor(
            headers={"server": "nginx", "content-type": "text/html"},
            body="<html><body>Hello</body></html>",
            domain="plain.com",
        )
        assert result.vendor == "none"
        assert result.confidence == 1.0

    def test_highest_confidence_wins(self):
        """When multiple vendors match, highest score should win."""
        # Cloudflare has strong header + cookie signals
        result = detect_vendor(
            headers={"cf-ray": "abc", "server": "cloudflare"},
            cookies={"cf_clearance": "xyz", "__cf_bm": "abc"},
            body="",
            domain="test.com",
        )
        assert "cloudflare" in result.vendor

    def test_recommended_tier_set(self):
        """Detection should include recommended evasion tier."""
        result = detect_vendor(
            headers={"cf-ray": "abc"},
            cookies={"cf_clearance": "xyz"},
            body='<div class="cf-turnstile"></div>',
            domain="test.com",
        )
        assert result.recommended_tier != ""

    def test_case_insensitive_headers(self):
        """Header matching should be case-insensitive."""
        result = detect_vendor(
            headers={"CF-Ray": "abc", "Server": "cloudflare"},
            domain="test.com",
        )
        assert "cloudflare" in result.vendor
