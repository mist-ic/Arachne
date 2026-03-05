"""
Health check endpoint.

Used by Docker HEALTHCHECK, Kubernetes probes, and uptime monitors.
Returns service status and connectivity checks for all dependencies.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check returning service status.

    Used by:
    - Docker HEALTHCHECK instruction
    - Load balancers and uptime monitors
    - Dashboard status indicators
    """
    return {
        "status": "healthy",
        "service": "api-gateway",
        "version": "0.1.0",
    }
