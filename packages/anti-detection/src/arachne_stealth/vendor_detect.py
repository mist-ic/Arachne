"""
Anti-bot vendor auto-detection.

Performs lightweight probe requests to identify which anti-bot vendor
protects a target domain. The detected vendor determines the starting
tier in the Evasion Router and selects the optimal bypass strategy.

Detection signals:
    - Response headers (cf-ray, x-datadome, akamai-grn, etc.)
    - Cookie names (cf_clearance, datadome, _abck, etc.)
    - HTML body patterns (challenge scripts, CAPTCHA providers)
    - JavaScript file URLs (challenge.cloudflare.com, etc.)

Once detected, results are cached per-domain and can be stored
in PostgreSQL for long-term analytics.

Research ref: Research.md §1.4 — Anti-bot vendor detection strategies
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VendorDetection:
    """Result of anti-bot vendor detection for a domain."""
    domain: str
    vendor: str                     # e.g., "cloudflare_turnstile"
    confidence: float               # 0.0-1.0
    signals: list[str] = field(default_factory=list)  # Evidence
    recommended_tier: str = ""
    raw_headers: dict[str, str] = field(default_factory=dict)


# =============================================================================
# Detection rules: header patterns, cookie names, body patterns
# =============================================================================

@dataclass
class VendorSignature:
    """Detection signature for an anti-bot vendor."""
    vendor: str
    display_name: str
    header_patterns: list[tuple[str, str]] = field(default_factory=list)  # (header_name, pattern)
    cookie_patterns: list[str] = field(default_factory=list)              # cookie name patterns
    body_patterns: list[str] = field(default_factory=list)                # HTML body regex patterns
    js_url_patterns: list[str] = field(default_factory=list)              # script src patterns
    recommended_tier: str = "HTTP_SPOOFED"


VENDOR_SIGNATURES: list[VendorSignature] = [
    VendorSignature(
        vendor="cloudflare_bot_management",
        display_name="Cloudflare Bot Management",
        header_patterns=[
            ("cf-ray", r".+"),
            ("cf-mitigated", r".+"),
            ("cf-chl-bypass", r".+"),
        ],
        cookie_patterns=["cf_clearance", "cf_chl_"],
        body_patterns=[
            r"challenge-platform",
            r"cdn-cgi/challenge-platform",
            r"Checking if the site connection is secure",
            r"ray ID",
        ],
        js_url_patterns=[r"challenges\.cloudflare\.com"],
        recommended_tier="BROWSER_ENGINE",
    ),
    VendorSignature(
        vendor="cloudflare_turnstile",
        display_name="Cloudflare Turnstile",
        header_patterns=[("cf-ray", r".+")],
        cookie_patterns=["cf_clearance"],
        body_patterns=[
            r"turnstile",
            r"challenges\.cloudflare\.com/turnstile",
            r'class="cf-turnstile"',
        ],
        js_url_patterns=[r"challenges\.cloudflare\.com/turnstile"],
        recommended_tier="BROWSER_CDP",
    ),
    VendorSignature(
        vendor="cloudflare_basic",
        display_name="Cloudflare Basic",
        header_patterns=[
            ("cf-ray", r".+"),
            ("server", r"cloudflare"),
        ],
        cookie_patterns=["__cf_bm"],
        body_patterns=[],
        recommended_tier="HTTP_SPOOFED",
    ),
    VendorSignature(
        vendor="akamai",
        display_name="Akamai Bot Manager",
        header_patterns=[
            ("x-akamai-transformed", r".+"),
            ("akamai-grn", r".+"),
            ("server", r"AkamaiGHost"),
        ],
        cookie_patterns=["_abck", "ak_bmsc", "bm_sz"],
        body_patterns=[
            r"_acPuzzleEncoder",
            r"akamaized\.net",
        ],
        recommended_tier="BROWSER_ENGINE",
    ),
    VendorSignature(
        vendor="datadome",
        display_name="DataDome",
        header_patterns=[
            ("x-datadome", r".+"),
            ("x-dd-b", r".+"),
            ("server", r"DataDome"),
        ],
        cookie_patterns=["datadome"],
        body_patterns=[
            r"datadome",
            r"dd\.js",
            r"geo\.captcha-delivery\.com",
        ],
        js_url_patterns=[r"js\.datadome\.co"],
        recommended_tier="BROWSER_ENGINE",
    ),
    VendorSignature(
        vendor="kasada",
        display_name="Kasada",
        header_patterns=[
            ("x-kpsdk-ct", r".+"),
            ("x-kpsdk-v", r".+"),
        ],
        cookie_patterns=["_kpsdk"],
        body_patterns=[
            r"ips\.js",
            r"kpsdk",
        ],
        recommended_tier="BROWSER_ENGINE",
    ),
    VendorSignature(
        vendor="perimeterx",
        display_name="HUMAN (PerimeterX)",
        header_patterns=[
            ("x-px-block", r".+"),
        ],
        cookie_patterns=["_px", "_pxhd", "_pxvid"],
        body_patterns=[
            r"perimeterx",
            r"px-captcha",
            r"human-challenge",
            r"captcha\.px-cdn\.net",
        ],
        recommended_tier="BROWSER_ENGINE",
    ),
    VendorSignature(
        vendor="aws_waf",
        display_name="AWS WAF",
        header_patterns=[
            ("x-amzn-waf-action", r".+"),
        ],
        cookie_patterns=["aws-waf-token"],
        body_patterns=[
            r"aws-waf",
            r"captcha\.awswaf\.com",
        ],
        recommended_tier="HTTP_SPOOFED",
    ),
    VendorSignature(
        vendor="recaptcha",
        display_name="Google reCAPTCHA",
        header_patterns=[],
        cookie_patterns=[],
        body_patterns=[
            r"google\.com/recaptcha",
            r"g-recaptcha",
            r"grecaptcha",
        ],
        js_url_patterns=[r"www\.google\.com/recaptcha"],
        recommended_tier="BROWSER_CDP",
    ),
    VendorSignature(
        vendor="hcaptcha",
        display_name="hCaptcha",
        header_patterns=[],
        cookie_patterns=[],
        body_patterns=[
            r"hcaptcha\.com",
            r"h-captcha",
        ],
        js_url_patterns=[r"hcaptcha\.com"],
        recommended_tier="BROWSER_CDP",
    ),
]


def detect_vendor(
    headers: dict[str, str],
    cookies: dict[str, str] | None = None,
    body: str = "",
    domain: str = "",
) -> VendorDetection:
    """Detect anti-bot vendor from response signals.

    Checks headers, cookies, and HTML body against known vendor
    signatures. Returns the vendor with highest confidence.

    Args:
        headers: HTTP response headers (case-insensitive keys).
        cookies: Response cookies (name → value).
        body: Response HTML body (or first 10KB for efficiency).
        domain: Target domain for the result.

    Returns:
        VendorDetection with vendor name, confidence, and signals.
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}
    cookies = cookies or {}
    # Only check first 10KB of body for performance
    body_sample = body[:10240]

    best_detection: VendorDetection | None = None
    best_score = 0

    for sig in VENDOR_SIGNATURES:
        signals = []
        score = 0

        # Check headers
        for header_name, pattern in sig.header_patterns:
            value = headers_lower.get(header_name.lower(), "")
            if value and re.search(pattern, value, re.IGNORECASE):
                signals.append(f"header:{header_name}={value[:50]}")
                score += 2

        # Check cookies
        for cookie_pattern in sig.cookie_patterns:
            for cookie_name in cookies:
                if cookie_pattern.lower() in cookie_name.lower():
                    signals.append(f"cookie:{cookie_name}")
                    score += 3  # Cookies are strong signals

        # Check body patterns
        for body_pattern in sig.body_patterns:
            if re.search(body_pattern, body_sample, re.IGNORECASE):
                signals.append(f"body:{body_pattern}")
                score += 1

        # Check JS URL patterns
        for js_pattern in sig.js_url_patterns:
            if re.search(js_pattern, body_sample, re.IGNORECASE):
                signals.append(f"script:{js_pattern}")
                score += 2

        if score > best_score:
            best_score = score
            # Normalize confidence (cap at 1.0)
            confidence = min(score / 8.0, 1.0)
            best_detection = VendorDetection(
                domain=domain,
                vendor=sig.vendor,
                confidence=confidence,
                signals=signals,
                recommended_tier=sig.recommended_tier,
                raw_headers=headers,
            )

    if best_detection:
        logger.info(
            f"Vendor detected for {domain}: {best_detection.vendor} "
            f"(confidence={best_detection.confidence:.2f}, signals={best_detection.signals})"
        )
        return best_detection

    return VendorDetection(
        domain=domain,
        vendor="none",
        confidence=1.0,
        signals=["No anti-bot vendor detected"],
        recommended_tier="HTTP_SPOOFED",
    )


async def probe_domain(domain: str) -> VendorDetection:
    """Probe a domain to detect its anti-bot vendor.

    Makes a lightweight curl_cffi HEAD/GET request and analyzes
    the response for vendor signatures.

    Args:
        domain: Domain to probe (e.g., "example.com").

    Returns:
        VendorDetection result.
    """
    from arachne_stealth.http_client import StealthHttpClient

    url = f"https://{domain}"
    client = StealthHttpClient()

    try:
        result = await client.fetch(url, session_key=f"_probe_{domain}")

        # Extract cookies from response headers
        cookies = {}
        set_cookie_values = result.headers.get("set-cookie", "")
        if set_cookie_values:
            for part in set_cookie_values.split(","):
                if "=" in part:
                    name = part.strip().split("=")[0].strip()
                    value = part.strip().split("=")[1].split(";")[0].strip()
                    cookies[name] = value

        return detect_vendor(
            headers=result.headers,
            cookies=cookies,
            body=result.html,
            domain=domain,
        )
    except Exception as e:
        logger.warning(f"Probe failed for {domain}: {e}")
        return VendorDetection(
            domain=domain,
            vendor="unknown",
            confidence=0.0,
            signals=[f"Probe error: {e}"],
            recommended_tier="BROWSER_CDP",  # Be cautious on probe failure
        )
    finally:
        await client.close_all()
