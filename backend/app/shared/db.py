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
from app.shared.rls_scopes import (
    ArtifactRlsScope as ArtifactRlsScope,
)
from app.shared.rls_scopes import (
    DirectorTurnRlsScope as DirectorTurnRlsScope,
)
from app.shared.rls_scopes import (
    NodeRunRlsScope as NodeRunRlsScope,
)
from app.shared.rls_scopes import (
    OutboxEventRlsScope as OutboxEventRlsScope,
)
from app.shared.rls_scopes import (
    list_pending_outbox_event_rls_scopes as list_pending_outbox_event_rls_scopes,
)
from app.shared.rls_scopes import (
    list_queued_node_run_rls_scopes as list_queued_node_run_rls_scopes,
)
from app.shared.rls_scopes import (
    list_reconcilable_director_turn_rls_scopes as list_reconcilable_director_turn_rls_scopes,
)
from app.shared.rls_scopes import (
    list_recoverable_director_turn_rls_scopes as list_recoverable_director_turn_rls_scopes,
)
from app.shared.rls_scopes import (
    list_resumable_provider_node_run_rls_scopes as list_resumable_provider_node_run_rls_scopes,
)
from app.shared.rls_scopes import (
    resolve_artifact_rls_scope as resolve_artifact_rls_scope,
)
from app.shared.rls_scopes import (
    resolve_node_run_rls_scope as resolve_node_run_rls_scope,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create or return the process-wide async engine."""
    global _engine, _session_factory
    if _engine is None:
        cfg = settings or get_settings()
        _engine = create_async_engine(
            cfg.database_url,
            pool_pre_ping=True,
            connect_args={"ssl": cfg.database_ssl},
        )
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
    workspace_id: UUID | None = None,
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
    await _set("app.current_workspace_id", workspace_id)
    await _set("app.current_project_id", project_id)


async def set_node_run_rls_context(
    session: AsyncSession,
    *,
    node_run_id: UUID,
) -> NodeRunRlsScope | None:
    """Apply the workspace-owner scope for one NodeRun to this transaction."""
    scope = await resolve_node_run_rls_scope(session, node_run_id=node_run_id)
    if scope is None:
        return None
    await set_rls_context(
        session,
        user_id=scope.user_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
    )
    return scope


async def set_artifact_rls_context(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    expected_workspace_id: UUID,
) -> ArtifactRlsScope | None:
    """Apply an Artifact's project scope only when it belongs to the workspace."""
    scope = await resolve_artifact_rls_scope(session, artifact_id=artifact_id)
    if scope is None or scope.workspace_id != expected_workspace_id:
        return None
    await set_rls_context(
        session,
        user_id=scope.user_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
    )
    return scope


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped session (no RLS until set)."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_session_with_rls(
    *,
    user_id: UUID | None = None,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Worker/service helper: open session and apply RLS GUC."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        yield session
