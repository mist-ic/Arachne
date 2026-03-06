"""
Pydoll browser backend — CDP-based Cloudflare Turnstile specialist.

Pydoll uses direct Chrome DevTools Protocol (CDP) connections with shadow root
and OOPIF (out-of-process iframe) traversal to auto-solve Cloudflare Turnstile
challenges without manual interaction.

Turnstile bypass algorithm (from RepoStudy §3):
    1. Find shadow root of the Turnstile widget
    2. Navigate into the challenge iframe
    3. Enter the iframe's shadow DOM
    4. Click the checkbox (span.cb-i)
    Uses DomCommands.get_document(depth=-1, pierce=True) and
    Target.attachToTarget for cross-origin iframes.

First-class cookie export makes this ideal for Browser→HTTP handoff:
obtain Cloudflare clearance via browser, then switch to fast curl_cffi.

Research ref: Research.md §1.3 — "Purpose-built for Cloudflare Turnstile bypass"
RepoStudy ref: RepoStudy §3 — Pydoll's shadow root traversal architecture
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from arachne_stealth.browser_backend import BrowserBackend, Cookie, PageResult

logger = logging.getLogger(__name__)


class PydollBackend(BrowserBackend):
    """Pydoll browser backend — Cloudflare Turnstile specialist.

    Stealth approach: Direct CDP connection with shadow root + OOPIF traversal
    for Cloudflare Turnstile auto-solve. No WebDriver layer — talks directly
    to Chrome via Chrome DevTools Protocol.

    Key features:
        - Built-in Cloudflare Turnstile auto-solve
        - First-class cookie export for Browser→HTTP handoff
        - Network request interception for API discovery
        - No WebDriver detection artifacts

    Tier: 2 (high stealth, specialized for Cloudflare)

    Usage:
        backend = PydollBackend()
        await backend.launch(headless=True)
        result = await backend.navigate("https://cloudflare-protected-site.com")
        cookies = await backend.get_cookies()  # CF clearance cookies
        await backend.close()
    """

    def __init__(self) -> None:
        self._browser = None
        self._page = None
        self._network_requests: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "Pydoll"

    @property
    def stealth_tier(self) -> int:
        return 2

    async def launch(self, **kwargs: Any) -> None:
        """Launch Chrome via Pydoll's CDP connection.

        Args:
            headless: Run headless (default True).
            proxy: Optional proxy URL string.
            auto_solve_cloudflare: Enable Turnstile auto-solve (default True).
        """
        try:
            from pydoll.browser.chromium import Chromium
            from pydoll.connection.options import Options
        except ImportError:
            raise RuntimeError(
                "Pydoll not installed. Install with: "
                "uv pip install 'arachne-stealth[browsers]'"
            )

        headless = kwargs.get("headless", True)
        proxy = kwargs.get("proxy")
        auto_solve = kwargs.get("auto_solve_cloudflare", True)

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        # Disable common automation flags
        options.add_argument("--disable-blink-features=AutomationControlled")

        logger.info(
            "Launching Pydoll (Chrome CDP)",
            extra={"headless": headless, "auto_solve": auto_solve},
        )

        self._browser = await Chromium(options=options).start()
        self._page = await self._browser.get_page()

        # Enable Cloudflare Turnstile auto-solve if requested
        if auto_solve:
            try:
                await self._page.enable_auto_solve_cloudflare_captcha()
                logger.info("Cloudflare Turnstile auto-solve enabled")
            except Exception as e:
                logger.warning(f"Could not enable Turnstile auto-solve: {e}")

        # Enable network interception for API discovery
        await self._setup_network_interception()

        logger.info("Pydoll launched")

    async def _setup_network_interception(self) -> None:
        """Set up CDP network event listeners for API discovery."""
        if self._page is None:
            return

        self._network_requests = []

        try:
            # Listen for network responses to capture XHR/fetch requests
            async def on_response(event: Any) -> None:
                try:
                    response_data = {
                        "url": getattr(event, "url", ""),
                        "status": getattr(event, "status", 0),
                        "mime_type": getattr(event, "mime_type", ""),
                        "headers": getattr(event, "headers", {}),
                    }
                    # Only capture JSON/API responses
                    mime = response_data.get("mime_type", "")
                    if "json" in mime or "javascript" in mime:
                        self._network_requests.append(response_data)
                except Exception:
                    pass  # Don't let listener errors break navigation

            await self._page.on("response", on_response)
        except Exception as e:
            logger.debug(f"Network interception setup skipped: {e}")

    async def navigate(
        self,
        url: str,
        wait_for: str | None = None,
        timeout: float = 30.0,
    ) -> PageResult:
        """Navigate to a URL with optional Cloudflare auto-solve.

        If a Cloudflare Turnstile challenge is encountered and auto-solve
        is enabled, Pydoll will automatically traverse the shadow DOM to
        click the challenge checkbox.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        start = perf_counter()

        # Navigate and wait for page load
        await self._page.go_to(url, timeout=int(timeout * 1000))

        if wait_for:
            await self._page.wait_element(wait_for, timeout=int(timeout * 1000))

        # Get page content
        html = await self._page.get_page_source()
        elapsed_ms = int((perf_counter() - start) * 1000)

        # Export cookies
        cookies = await self.get_cookies()

        logger.info(
            "Pydoll navigated",
            extra={"url": url, "elapsed_ms": elapsed_ms},
        )

        return PageResult(
            url=url,
            html=html,
            status_code=200,  # Pydoll doesn't directly expose status codes
            cookies=cookies,
            headers={},
            elapsed_ms=elapsed_ms,
            network_requests=list(self._network_requests),
        )

    async def get_cookies(self) -> list[Cookie]:
        """Export cookies from the Chrome browser.

        Pydoll provides first-class cookie export, making it ideal for
        the Browser→HTTP handoff pattern.
        """
        if self._page is None:
            return []

        try:
            raw_cookies = await self._page.get_cookies()
        except Exception:
            return []

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
            raise RuntimeError("Browser not launched.")
        return await self._page.get_screenshot()

    async def close(self) -> None:
        """Close browser and clean up."""
        if self._browser:
            try:
                await self._browser.stop()
            except Exception:
                pass
        self._page = None
        self._browser = None
        self._network_requests = []
        logger.info("Pydoll closed")

    async def execute_js(self, script: str) -> Any:
        """Execute JavaScript via CDP."""
        if self._page is None:
            raise RuntimeError("Browser not launched.")
        return await self._page.execute_script(script)

    async def get_network_requests(self) -> list[dict[str, Any]]:
        """Get captured network requests for API discovery."""
        return list(self._network_requests)
