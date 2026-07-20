"""Database engine, session factory, and RLS transaction context."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import text
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


async def set_rls_context(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
) -> None:
    """SET LOCAL app.* for the current transaction (PostgreSQL). No-op on SQLite."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect != "postgresql":
        return
    # SET LOCAL does not support bind params for GUC in all drivers — quote carefully.
    async def _set(key: str, value: UUID | None) -> None:
        if value is None:
            await session.execute(text(f"SELECT set_config('{key}', '', true)"))
        else:
            await session.execute(
                text("SELECT set_config(:k, :v, true)"),
                {"k": key, "v": str(value)},
            )

    await _set("app.current_user_id", user_id)
    await _set("app.current_organization_id", organization_id)
    await _set("app.current_project_id", project_id)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped session (no RLS until set)."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_session_with_rls(
    *,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Worker/service helper: open session and apply RLS GUC."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=user_id,
            organization_id=organization_id,
            project_id=project_id,
        )
        yield session
