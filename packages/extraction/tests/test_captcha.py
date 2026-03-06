"""
Tests for CAPTCHA detection and solver interfaces.
"""

from __future__ import annotations

import pytest

from arachne_extraction.captcha.solver import (
    CaptchaSolution,
    CaptchaSolver,
    CaptchaType,
    SolveMethod,
    detect_captcha_type,
    is_challenge_page,
)


# ============================================================================
# CAPTCHA Detection Tests
# ============================================================================


class TestCaptchaDetection:
    """Tests for CAPTCHA type detection from HTML content."""

    def test_detects_recaptcha_v2(self):
        html = '<script src="https://www.google.com/recaptcha/api.js"></script>'
        assert detect_captcha_type(html) == CaptchaType.RECAPTCHA_V2

    def test_detects_recaptcha_class(self):
        html = '<div class="g-recaptcha" data-sitekey="key123"></div>'
        assert detect_captcha_type(html) == CaptchaType.RECAPTCHA_V2

    def test_detects_hcaptcha(self):
        html = '<script src="https://hcaptcha.com/1/api.js"></script>'
        assert detect_captcha_type(html) == CaptchaType.HCAPTCHA

    def test_detects_hcaptcha_class(self):
        html = '<div class="h-captcha" data-sitekey="key456"></div>'
        assert detect_captcha_type(html) == CaptchaType.HCAPTCHA

    def test_detects_cloudflare_turnstile(self):
        html = '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
        assert detect_captcha_type(html) == CaptchaType.CLOUDFLARE_TURNSTILE

    def test_detects_cf_turnstile_class(self):
        html = '<div class="cf-turnstile"></div>'
        assert detect_captcha_type(html) == CaptchaType.CLOUDFLARE_TURNSTILE

    def test_detects_geetest(self):
        html = '<script src="https://static.geetest.com/static/gt_lib.js"></script>'
        assert detect_captcha_type(html) == CaptchaType.GEETEST

    def test_detects_geetest_init(self):
        html = '<script>initGeetest({gt: "abc123"});</script>'
        assert detect_captcha_type(html) == CaptchaType.GEETEST

    def test_detects_funcaptcha(self):
        html = '<script src="https://client-api.arkoselabs.com/fc/assets/ec-game-core/"></script>'
        assert detect_captcha_type(html) == CaptchaType.FUNCAPTCHA

    def test_detects_challenge_page(self):
        html = """
        <html>
        <body>
            <h1>Checking your browser before accessing...</h1>
            <p>This process is automatic.</p>
        </body>
        </html>
        """
        result = detect_captcha_type(html)
        assert result == CaptchaType.UNKNOWN

    def test_detects_verification_page(self):
        html = "<h1>Please verify you are a human</h1>"
        result = detect_captcha_type(html)
        assert result == CaptchaType.UNKNOWN

    def test_no_captcha_on_clean_page(self):
        html = """
        <html>
        <body>
            <h1>Welcome to our website</h1>
            <p>Great products at great prices.</p>
        </body>
        </html>
        """
        assert detect_captcha_type(html) is None

    def test_empty_html(self):
        assert detect_captcha_type("") is None

    def test_none_input(self):
        assert detect_captcha_type(None) is None


# ============================================================================
# Challenge Page Detection Tests
# ============================================================================


class TestIsChallengePage:
    """Tests for the quick challenge page check."""

    def test_captcha_page_is_challenge(self):
        html = '<div class="g-recaptcha" data-sitekey="key123"></div>'
        assert is_challenge_page(html) is True

    def test_normal_page_not_challenge(self):
        html = "<html><body><h1>Normal Page</h1></body></html>"
        assert is_challenge_page(html) is False


# ============================================================================
# CaptchaSolution Model Tests
# ============================================================================


class TestCaptchaSolution:
    """Tests for the CaptchaSolution data model."""

    def test_successful_solution(self):
        solution = CaptchaSolution(
            solved=True,
            captcha_type=CaptchaType.RECAPTCHA_V2,
            method=SolveMethod.EXTERNAL_API,
            solution_data={"g-recaptcha-response": "token123"},
            solve_time_ms=5000,
            confidence=0.95,
            cost_usd=0.003,
        )
        assert solution.solved is True
        assert solution.cost_usd == 0.003

    def test_failed_solution(self):
        solution = CaptchaSolution(
            solved=False,
            captcha_type=CaptchaType.IMAGE_GRID,
            method=SolveMethod.LOCAL_VISION,
            error="Model not loaded",
        )
        assert solution.solved is False
        assert solution.error == "Model not loaded"

    def test_unsolvable(self):
        solution = CaptchaSolution(
            solved=False,
            captcha_type=CaptchaType.UNKNOWN,
            method=SolveMethod.UNSOLVABLE,
            error="All solvers exhausted",
        )
        assert solution.method == SolveMethod.UNSOLVABLE


# ============================================================================
# CaptchaType Enum Tests
# ============================================================================


class TestCaptchaType:
    """Tests for CaptchaType enum values."""

    def test_all_types_have_values(self):
        assert CaptchaType.IMAGE_GRID == "image_grid"
        assert CaptchaType.SLIDER == "slider"
        assert CaptchaType.TEXT_MATH == "text_math"
        assert CaptchaType.ROTATE == "rotate"
        assert CaptchaType.RECAPTCHA_V2 == "recaptcha_v2"
        assert CaptchaType.HCAPTCHA == "hcaptcha"
        assert CaptchaType.GEETEST == "geetest"
        assert CaptchaType.CLOUDFLARE_TURNSTILE == "cloudflare_turnstile"
        assert CaptchaType.FUNCAPTCHA == "funcaptcha"
        assert CaptchaType.UNKNOWN == "unknown"
