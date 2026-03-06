"""
Camoufox browser backend — C++-patched Firefox for maximum stealth.

Camoufox is a custom Firefox build where fingerprint signals are patched at
the C++ level (MaskConfig.hpp), making it fundamentally more evasive than
JavaScript injection approaches which CreepJS's lies/ module detects.

Combined with BrowserForge for Bayesian fingerprint generation (prevents
impossible combos like macOS UA + Windows GPU), this is the highest-tier
stealth browser available.

Research ref: Research.md §1.3 — "The most advanced open-source stealth
approach. Near 0% detection on CreepJS-type tests."
RepoStudy ref: RepoStudy §7 — Camoufox architecture and MaskConfig.hpp.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from arachne_stealth.browser_backend import BrowserBackend, Cookie, PageResult

logger = logging.getLogger(__name__)


class CamoufoxBackend(BrowserBackend):
    """Camoufox browser backend — engine-modded Firefox.

    Stealth approach: C++ engine modification (28 fingerprint signals patched
    at the browser engine level). This is fundamentally different from JS
    injection — there are no JavaScript API overrides to detect.

    Key features:
        - BrowserForge Bayesian fingerprint generation
        - "Headful headless" mode via virtual display (Xvfb)
        - Playwright-compatible API
        - Remote server mode for distributed deployment

    Tier: 3 (highest stealth in the escalation ladder)

    Usage:
        backend = CamoufoxBackend()
        await backend.launch(headless=True)
        result = await backend.navigate("https://example.com")
        cookies = await backend.get_cookies()
        await backend.close()
    """

    def __init__(self) -> None:
        self._browser = None
        self._context = None
        self._page = None

    @property
    def name(self) -> str:
        return "Camoufox"

    @property
    def stealth_tier(self) -> int:
        return 3

    async def launch(self, **kwargs: Any) -> None:
        """Launch Camoufox with BrowserForge fingerprint.

        Args:
            headless: Run headless (default True). Uses Xvfb in Docker
                      for "headful headless" mode.
            proxy: Optional proxy dict {"server": "http://...", ...}.
            humanize: Enable built-in humanization (default True).
        """
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            raise RuntimeError(
                "Camoufox not installed. Install with: "
                "uv pip install 'arachne-stealth[browsers]'"
            )

        headless = kwargs.get("headless", True)
        proxy = kwargs.get("proxy")
        humanize = kwargs.get("humanize", True)

        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "humanize": humanize,
        }

        if proxy:
            launch_kwargs["proxy"] = proxy

        logger.info(
            "Launching Camoufox",
            extra={"headless": headless, "humanize": humanize},
        )

        # AsyncCamoufox returns a Playwright browser with patched fingerprints
        # BrowserForge generates statistically accurate, consistent fingerprints
        self._camoufox_cm = AsyncCamoufox(**launch_kwargs)
        self._browser = await self._camoufox_cm.__aenter__()
        self._context = self._browser
        self._page = await self._browser.new_page()

        logger.info("Camoufox launched with BrowserForge fingerprint")

    async def navigate(
        self,
        url: str,
        wait_for: str | None = None,
        timeout: float = 30.0,
    ) -> PageResult:
        """Navigate to a URL using Camoufox.

        Camoufox uses a Playwright-compatible API, so navigation follows
        the standard Playwright page.goto() pattern.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        start = perf_counter()
        timeout_ms = int(timeout * 1000)

        response = await self._page.goto(
            url,
            timeout=timeout_ms,
            wait_until="domcontentloaded",
        )

        if wait_for:
            await self._page.wait_for_selector(wait_for, timeout=timeout_ms)

        html = await self._page.content()
        elapsed_ms = int((perf_counter() - start) * 1000)

        # Get response info
        status_code = response.status if response else 0
        headers = dict(response.headers) if response else {}

        # Export cookies
        cookies = await self.get_cookies()

        logger.info(
            "Camoufox navigated",
            extra={"url": url, "status": status_code, "elapsed_ms": elapsed_ms},
        )

        return PageResult(
            url=url,
            html=html,
            status_code=status_code,
            cookies=cookies,
            headers=headers,
            elapsed_ms=elapsed_ms,
        )

    async def get_cookies(self) -> list[Cookie]:
        """Export cookies from the Camoufox browser context."""
        if self._page is None:
            return []

        context = self._page.context
        raw_cookies = await context.cookies()

        return [
            Cookie(
                name=c.get("name", ""),
                value=c.get("value", ""),
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
                expires=c.get("expires", -1),
                http_only=c.get("httpOnly", False),
                secure=c.get("secure", False),
                same_site=c.get("sameSite", "Lax"),
            )
            for c in raw_cookies
        ]

    async def screenshot(self) -> bytes:
        """Capture a full-page screenshot."""
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return await self._page.screenshot(full_page=True, type="png")

    async def close(self) -> None:
        """Close browser and clean up."""
        if self._camoufox_cm:
            try:
                await self._camoufox_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        logger.info("Camoufox closed")

    async def execute_js(self, script: str) -> Any:
        """Execute JavaScript in the page context via Playwright API."""
        if self._page is None:
            raise RuntimeError("Browser not launched.")
        return await self._page.evaluate(script)
