"""CAPTCHA solving package — local vision and external API solvers."""

from arachne_extraction.captcha.solver import (
    CaptchaSolution,
    CaptchaSolver,
    CaptchaType,
    detect_captcha_type,
)

__all__ = [
    "CaptchaSolution",
    "CaptchaSolver",
    "CaptchaType",
    "detect_captcha_type",
]
