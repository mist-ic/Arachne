"""
Arachne API Gateway — FastAPI application entry point.

The API gateway is the single entry point for all client requests.
It handles:
- Job submission and status tracking (CRUD)
- Temporal workflow dispatch (start scrape workflows)
- Health checks (for Docker/Kubernetes readiness probes)

Architecture: Domain-based structure
    src/
    ├── main.py          ← This file (app factory + lifespan)
    ├── config.py        ← Pydantic settings
    ├── dependencies.py  ← FastAPI dependency injection
    └── routers/
        ├── jobs.py      ← /api/v1/jobs endpoints
        └── health.py    ← /api/v1/health endpoint
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import APIConfig
from dependencies import init_services, shutdown_services
from routers import health, jobs

config = APIConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager.

    Startup: Connect to PostgreSQL, Temporal, and initialize services.
    Shutdown: Close connections and clean up resources.

    FastAPI's lifespan replaces the deprecated @app.on_event("startup").
    """
    await init_services(config)
    yield
    await shutdown_services()


app = FastAPI(
    title="Arachne API",
    description=(
        "Web intelligence platform with production-grade anti-detection, "
        "AI-first extraction, and distributed pipeline architecture."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Mount routers
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API docs."""
    return {"message": "Arachne API", "docs": "/docs"}
