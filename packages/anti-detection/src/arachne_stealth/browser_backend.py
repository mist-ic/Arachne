"""
Abstract browser backend interface.

Defines the contract that all stealth browser backends must implement.
This clean interface demonstrates dependency inversion — the Evasion Router
doesn't know about specific browser tools, only this interface.

Backends:
    - CamoufoxBackend: C++-patched Firefox, highest stealth (near 0% CreepJS)
    - PydollBackend: CDP-based, Cloudflare Turnstile specialist
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Cookie:
    """Browser cookie representation for handoff between browser and HTTP."""
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: float = -1
    http_only: bool = False
    secure: bool = False
    same_site: str = "Lax"


@dataclass
class PageResult:
    """Result of a browser page navigation."""
    url: str
    html: str
    status_code: int
    cookies: list[Cookie] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    screenshot: bytes | None = None
    network_requests: list[dict[str, Any]] = field(default_factory=list)


class BrowserBackend(ABC):
    """Abstract interface for stealth browser backends.

    All browser backends implement this interface so the Evasion Router
    can select, launch, and use any backend interchangeably. This is
    the key architectural demonstration — pluggable systems via
    dependency inversion.

    Lifecycle:
        1. launch() → Initialize browser with a fingerprint profile
        2. navigate(url) → Load a page with optional wait conditions
        3. get_cookies() → Export cookies for Browser→HTTP handoff
        4. screenshot() → Capture page screenshot (for debugging/CV)
        5. close() → Clean up resources
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (e.g., 'Camoufox', 'Pydoll')."""
        ...

    @property
    @abstractmethod
    def stealth_tier(self) -> int:
        """Stealth tier in the escalation ladder (higher = more evasive).

        Tier mapping:
            1 = Basic patched browser (Patchright/rebrowser)
            2 = Direct CDP post-WebDriver (Nodriver/Pydoll)
            3 = Engine-modded browser (Camoufox with BrowserForge)
        """
        ...

    @abstractmethod
    async def launch(self, **kwargs: Any) -> None:
        """Initialize the browser with optional configuration.

        Args:
            **kwargs: Backend-specific config (headless, proxy, viewport, etc.)
        """
        ...

    @abstractmethod
    async def navigate(
        self,
        url: str,
        wait_for: str | None = None,
        timeout: float = 30.0,
    ) -> PageResult:
        """Navigate to a URL and return the page content.

        Args:
            url: Target URL.
            wait_for: Optional CSS selector to wait for before returning.
            timeout: Navigation timeout in seconds.

        Returns:
            PageResult with HTML, cookies, status, and optional screenshot.
        """
        ...

    @abstractmethod
    async def get_cookies(self) -> list[Cookie]:
        """Export all cookies from the current browser context.

        Used for Browser→HTTP handoff: cookies obtained via browser session
        are exported and injected into curl_cffi for fast HTTP requests.
        """
        ...

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Capture a full-page screenshot as PNG bytes.

        Used for debugging, visual change detection, and Phase 3/4
        computer vision pipelines (SAM 3, RF-DETR).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the browser and clean up all resources."""
        ...

    async def execute_js(self, script: str) -> Any:
        """Execute JavaScript in the page context.

        Default implementation raises NotImplementedError. Backends
        that support JS execution should override this.

        Args:
            script: JavaScript code to execute.

        Returns:
            The result of the script execution.
        """
        raise NotImplementedError(f"{self.name} does not support JS execution")

    async def get_network_requests(self) -> list[dict[str, Any]]:
        """Get captured network requests (for API discovery).

        Default implementation returns empty list. Backends that support
        network interception should override this.
        """
        return []
