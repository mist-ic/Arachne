"""
CAPTCHA solver abstraction and detection.

Defines the CaptchaSolver interface implemented by both LocalVisionSolver
(Qwen3-VL via Ollama) and ExternalAPISolver (2Captcha, CapSolver).
Also provides CAPTCHA type detection from HTML content.

References:
    - Research.md §1.4: CAPTCHA solving strategies
    - Phase3.md Steps 4 + 6: Local and external solving
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class CaptchaType(StrEnum):
    """Types of CAPTCHAs we can encounter and solve."""

    IMAGE_GRID = "image_grid"  # reCAPTCHA v2: "click all traffic lights"
    SLIDER = "slider"  # GeeTest slider puzzles
    TEXT_MATH = "text_math"  # Text or math CAPTCHAs
    ROTATE = "rotate"  # Rotation CAPTCHAs
    RECAPTCHA_V2 = "recaptcha_v2"  # Google reCAPTCHA v2 checkbox + image
    HCAPTCHA = "hcaptcha"  # hCaptcha image selection
    GEETEST = "geetest"  # GeeTest multi-type challenges
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"  # Handled by Pydoll (Phase 2)
    FUNCAPTCHA = "funcaptcha"  # Arkose Labs FunCaptcha
    UNKNOWN = "unknown"


class SolveMethod(StrEnum):
    """How the CAPTCHA was solved."""

    LOCAL_VISION = "local_vision"  # Qwen3-VL via Ollama
    EXTERNAL_API = "external_api"  # 2Captcha, CapSolver, etc.
    BROWSER_AUTO = "browser_auto"  # Pydoll/Camoufox auto-solve
    UNSOLVABLE = "unsolvable"  # Could not be solved


@dataclass
class CaptchaSolution:
    """Result of a CAPTCHA solving attempt."""

    solved: bool  # Whether the CAPTCHA was successfully solved
    captcha_type: CaptchaType
    method: SolveMethod
    solution_data: dict = field(default_factory=dict)  # Type-specific solution
    solve_time_ms: int = 0
    confidence: float = 0.0  # 0-1, how confident we are in the solution
    cost_usd: float = 0.0  # Cost of solving ($0 for local)
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Type-specific solution data keys:
    # IMAGE_GRID: {"selected_cells": [0, 3, 6, 7]}
    # SLIDER: {"offset_x": 142}
    # TEXT_MATH: {"text": "7G9Kp"}
    # ROTATE: {"angle": 127}
    # RECAPTCHA_V2: {"g-recaptcha-response": "03AGdBq..."}
    # HCAPTCHA: {"h-captcha-response": "P0_eyJ..."}


# ============================================================================
# CAPTCHA Solver Interface
# ============================================================================


class CaptchaSolver(ABC):
    """Abstract interface for CAPTCHA solvers.

    Implemented by LocalVisionSolver (Qwen3-VL) and ExternalAPISolver
    (2Captcha, CapSolver). The Evasion Router uses this interface to
    solve CAPTCHAs detected during browser sessions.
    """

    @abstractmethod
    async def solve(
        self,
        image: bytes,
        captcha_type: CaptchaType,
        *,
        site_key: str | None = None,
        page_url: str | None = None,
        extra_params: dict | None = None,
    ) -> CaptchaSolution:
        """Solve a CAPTCHA.

        Args:
            image: Screenshot of the CAPTCHA element (PNG bytes).
            captcha_type: Type of CAPTCHA detected.
            site_key: reCAPTCHA/hCaptcha site key (for token-based solving).
            page_url: URL where the CAPTCHA appears.
            extra_params: Provider-specific parameters.

        Returns:
            CaptchaSolution with solution data or error.
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this solver is currently available.

        LocalVisionSolver checks if Ollama is running with the model loaded.
        ExternalAPISolver checks if API keys are configured and balance is sufficient.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable solver name for logging."""
        ...


# ============================================================================
# CAPTCHA Detection
# ============================================================================


# Detection patterns for known CAPTCHA providers
_CAPTCHA_PATTERNS: dict[CaptchaType, list[re.Pattern]] = {
    CaptchaType.RECAPTCHA_V2: [
        re.compile(r"google\.com/recaptcha", re.IGNORECASE),
        re.compile(r"g-recaptcha", re.IGNORECASE),
        re.compile(r"grecaptcha", re.IGNORECASE),
        re.compile(r'class="g-recaptcha"', re.IGNORECASE),
        re.compile(r"recaptcha/api\.js", re.IGNORECASE),
    ],
    CaptchaType.HCAPTCHA: [
        re.compile(r"hcaptcha\.com", re.IGNORECASE),
        re.compile(r"h-captcha", re.IGNORECASE),
        re.compile(r'class="h-captcha"', re.IGNORECASE),
        re.compile(r"hcaptcha\.com/1/api\.js", re.IGNORECASE),
    ],
    CaptchaType.CLOUDFLARE_TURNSTILE: [
        re.compile(r"challenges\.cloudflare\.com", re.IGNORECASE),
        re.compile(r"cf-turnstile", re.IGNORECASE),
        re.compile(r"turnstile/v0/api\.js", re.IGNORECASE),
    ],
    CaptchaType.GEETEST: [
        re.compile(r"geetest\.com", re.IGNORECASE),
        re.compile(r"geetest_", re.IGNORECASE),
        re.compile(r"gt_lib", re.IGNORECASE),
        re.compile(r"initGeetest", re.IGNORECASE),
    ],
    CaptchaType.FUNCAPTCHA: [
        re.compile(r"funcaptcha\.com", re.IGNORECASE),
        re.compile(r"arkoselabs\.com", re.IGNORECASE),
        re.compile(r"client-api\.arkoselabs", re.IGNORECASE),
    ],
}

# Challenge page patterns (not specific CAPTCHAs but protection challenges)
_CHALLENGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"Checking your browser", re.IGNORECASE),
    re.compile(r"Just a moment\.\.\.", re.IGNORECASE),
    re.compile(r"Please verify you are a human", re.IGNORECASE),
    re.compile(r"Access denied", re.IGNORECASE),
    re.compile(r"blocked", re.IGNORECASE),
]


def detect_captcha_type(html: str) -> CaptchaType | None:
    """Detect what type of CAPTCHA is present in the HTML.

    Checks response HTML for known CAPTCHA script sources, DOM elements,
    and challenge page patterns.

    Args:
        html: Raw HTML content of the page.

    Returns:
        Detected CaptchaType, or None if no CAPTCHA found.
    """
    if not html:
        return None

    for captcha_type, patterns in _CAPTCHA_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(html):
                logger.info(
                    "captcha_detected",
                    type=captcha_type,
                    pattern=pattern.pattern[:50],
                )
                return captcha_type

    # Check for generic challenge pages
    for pattern in _CHALLENGE_PATTERNS:
        if pattern.search(html):
            logger.info("challenge_page_detected", pattern=pattern.pattern[:50])
            return CaptchaType.UNKNOWN

    return None


def is_challenge_page(html: str) -> bool:
    """Quick check if the HTML is a challenge/CAPTCHA page rather than content.

    Useful for the Evasion Router to decide whether to escalate.
    """
    return detect_captcha_type(html) is not None
