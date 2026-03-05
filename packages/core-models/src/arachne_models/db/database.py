"""
SQLAlchemy async database engine and session management.

Provides the async engine, session factory, and base model class used
across all services. Each service calls init_db() once at startup to
create the engine, then uses get_session() to get scoped sessions.

Uses SQLAlchemy 2.0+ with:
- AsyncAttrs mixin for lazy-load support in async context
- async_sessionmaker for session creation
- asyncpg as the PostgreSQL driver (fastest async PG driver)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Default DSN for local development
DEFAULT_DSN = "postgresql+asyncpg://arachne:arachne@localhost:5432/arachne"


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy ORM models.

    AsyncAttrs mixin allows lazy-loading relationships in async context
    (e.g. await job.awaitable_attrs.entities instead of eager loading).
    """
    pass


# Module-level engine and session factory (initialized by init_db)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(dsn: str = DEFAULT_DSN, echo: bool = False) -> AsyncEngine:
    """Initialize the async database engine and session factory.

    Call once at application startup (e.g. in FastAPI lifespan or
    Temporal worker main).

    Args:
        dsn: PostgreSQL connection string with asyncpg driver.
        echo: If True, log all SQL statements (useful for debugging).

    Returns:
        The created AsyncEngine.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        dsn,
        echo=echo,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,  # Verify connections before using them
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Don't expire attributes after commit
    )

    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session.

    Used as a FastAPI dependency:
        async def my_endpoint(db: AsyncSession = Depends(get_session)):

    Sessions are automatically committed on success and rolled back
    on exception.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose of the engine and connection pool.

    Call at application shutdown.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
