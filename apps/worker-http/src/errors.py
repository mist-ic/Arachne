"""
Custom HTTP error types for Temporal retry routing.

Temporal's retry policy supports `non_retryable_error_types` — a list of
error class names that should NOT be retried. This lets us implement
intelligent error routing:

    - 403 Forbidden → Retry with backoff (Phase 2: escalate to browser)
    - 429 Rate Limited → Retry with exponential backoff
    - 503 Server Error → Retry (transient)
    - 404 Not Found → NO retry (dead resource)
    - 401/407 Auth Required → NO retry (needs credentials)
    - Network errors → Retry with backoff (transient)

By raising typed exceptions, Temporal automatically knows which errors
are retryable and which should fail the workflow immediately.
"""

from __future__ import annotations


class FetchError(Exception):
    """Base class for all fetch-related errors."""

    def __init__(self, message: str, status_code: int | None = None, url: str = "") -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message)


# ---------------------------------------------------------------------------
# Retryable errors — Temporal will retry these with backoff
# ---------------------------------------------------------------------------

class HTTP403Error(FetchError):
    """Blocked by anti-bot protection. Retryable because Phase 2 escalates
    to stealth browser on retry."""
    pass


class HTTP429Error(FetchError):
    """Rate limited. Retryable with exponential backoff."""
    pass


class HTTP503Error(FetchError):
    """Server temporarily overloaded. Retryable."""
    pass


class NetworkError(FetchError):
    """Connection timeout, DNS failure, etc. Retryable."""
    pass


# ---------------------------------------------------------------------------
# Non-retryable errors — these fail the workflow immediately
# ---------------------------------------------------------------------------

class HTTP404Error(FetchError):
    """Resource not found. Dead URL, no point retrying."""
    pass


class HTTP401Error(FetchError):
    """Authentication required. Cannot proceed without credentials."""
    pass


class HTTP407Error(FetchError):
    """Proxy authentication required."""
    pass
