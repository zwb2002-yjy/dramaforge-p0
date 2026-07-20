"""Database engine and session factory shells (wired fully in S1)."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create or return the process-wide async engine."""
    global _engine, _session_factory
    if _engine is None:
        cfg = settings or get_settings()
        _engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the async session factory, creating the engine if needed."""
    global _session_factory
    if _session_factory is None:
        get_engine(settings)
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
