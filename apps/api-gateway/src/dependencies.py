"""
FastAPI dependency injection.

Centralizes all service initialization and dependency providers.
FastAPI's Depends() system injects these into route handlers,
making them testable (swap real DB for mock in tests).

Services initialized at startup (lifespan):
    - Database engine + session factory
    - Temporal client connection
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client as TemporalClient

from arachne_models.db.database import close_db, get_session, init_db
from config import APIConfig

# Module-level state (initialized in lifespan)
_temporal_client: TemporalClient | None = None
_config: APIConfig | None = None


async def init_services(config: APIConfig) -> None:
    """Initialize all external service connections.

    Called once during FastAPI lifespan startup.
    """
    global _temporal_client, _config
    _config = config

    # Initialize database
    init_db(dsn=config.postgres_dsn, echo=config.debug)

    # Connect to Temporal
    _temporal_client = await TemporalClient.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
    )


async def shutdown_services() -> None:
    """Clean up all service connections.

    Called during FastAPI lifespan shutdown.
    """
    await close_db()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session to route handlers.

    Usage in routes:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    async for session in get_session():
        yield session


def get_temporal() -> TemporalClient:
    """Provide the Temporal client to route handlers.

    Usage in routes:
        async def start_job(temporal: TemporalClient = Depends(get_temporal)):
    """
    if _temporal_client is None:
        raise RuntimeError("Temporal client not initialized")
    return _temporal_client


def get_config() -> APIConfig:
    """Provide the API config to route handlers."""
    if _config is None:
        raise RuntimeError("Config not initialized")
    return _config
