"""Database engine, session factory, and RLS transaction context."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True)
class NodeRunRlsScope:
    """Ownership context reconstructed from NodeRun -> Project -> Workspace."""

    user_id: UUID
    workspace_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class OutboxEventRlsScope:
    """Ownership context reconstructed from an outbox event's project."""

    event_id: UUID
    user_id: UUID | None
    workspace_id: UUID | None
    project_id: UUID | None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create or return the process-wide async engine."""
    global _engine, _session_factory
    if _engine is None:
        cfg = settings or get_settings()
        # Local/dev asyncpg: disable TLS handshake (common behind WSL/port proxies).
        _engine = create_async_engine(
            cfg.database_url,
            pool_pre_ping=True,
            connect_args={"ssl": False},
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


async def resolve_node_run_rls_scope(
    session: AsyncSession,
    *,
    node_run_id: UUID,
) -> NodeRunRlsScope | None:
    """Resolve worker ownership from persisted records, never queue payloads."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        result = await session.execute(
            text(
                """
                SELECT owner_user_id, workspace_id, project_id
                FROM app.node_run_context(:node_run_id)
                """
            ),
            {"node_run_id": node_run_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return NodeRunRlsScope(
            user_id=row["owner_user_id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
        )

    from app.access.models import Project, Workspace
    from app.execution.models import NodeRun

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        return None
    project = await session.get(Project, run.project_id)
    if project is None:
        return None
    workspace = await session.get(Workspace, project.workspace_id)
    if workspace is None:
        return None
    return NodeRunRlsScope(
        user_id=workspace.owner_user_id,
        workspace_id=workspace.id,
        project_id=project.id,
    )


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


async def list_queued_node_run_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    project_id: UUID | None = None,
) -> list[tuple[UUID, NodeRunRlsScope]]:
    """Find queued work and ownership through the narrowly scoped DB resolver."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        result = await session.execute(
            text(
                """
                SELECT node_run_id, owner_user_id, workspace_id, project_id
                FROM app.queued_node_run_contexts(:limit, :project_id)
                """
            ),
            {"limit": limit, "project_id": project_id},
        )
        return [
            (
                row["node_run_id"],
                NodeRunRlsScope(
                    user_id=row["owner_user_id"],
                    workspace_id=row["workspace_id"],
                    project_id=row["project_id"],
                ),
            )
            for row in result.mappings().all()
        ]

    from sqlalchemy import select

    from app.execution.models import NodeRun

    stmt = (
        select(NodeRun.id)
        .where(NodeRun.status == "queued")
        .order_by(NodeRun.created_at, NodeRun.id)
        .limit(limit)
    )
    if project_id is not None:
        stmt = stmt.where(NodeRun.project_id == project_id)
    result = await session.execute(stmt)
    scopes: list[tuple[UUID, NodeRunRlsScope]] = []
    for node_run_id in result.scalars().all():
        scope = await resolve_node_run_rls_scope(session, node_run_id=node_run_id)
        if scope is not None:
            scopes.append((node_run_id, scope))
    return scopes


async def list_pending_outbox_event_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    project_id: UUID | None = None,
) -> list[OutboxEventRlsScope]:
    """Find dispatchable events with ownership resolved independently of RLS context."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        result = await session.execute(
            text(
                """
                SELECT outbox_event_id, owner_user_id, workspace_id, project_id
                FROM app.pending_outbox_event_contexts(:limit, :project_id)
                """
            ),
            {"limit": limit, "project_id": project_id},
        )
        return [
            OutboxEventRlsScope(
                event_id=row["outbox_event_id"],
                user_id=row["owner_user_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
            )
            for row in result.mappings().all()
        ]

    from datetime import UTC, datetime

    from app.events.models import OutboxEvent
    from app.shared.enums import OutboxStatus

    now = datetime.now(UTC)
    stmt = (
        select(OutboxEvent)
        .where(
            or_(
                (OutboxEvent.status == OutboxStatus.PENDING.value)
                & (OutboxEvent.next_attempt_at <= now),
                (OutboxEvent.status == OutboxStatus.LEASED.value)
                & (OutboxEvent.leased_until < now),
            )
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.event_id)
        .limit(limit)
    )
    if project_id is not None:
        stmt = stmt.where(OutboxEvent.project_id == project_id)
    result = await session.execute(stmt)
    scopes: list[OutboxEventRlsScope] = []
    for event in result.scalars().all():
        if event.project_id is None:
            scopes.append(
                OutboxEventRlsScope(
                    event_id=event.event_id,
                    user_id=None,
                    workspace_id=None,
                    project_id=None,
                )
            )
            continue
        from app.access.models import Project, Workspace

        project = await session.get(Project, event.project_id)
        if project is None:
            continue
        workspace = await session.get(Workspace, project.workspace_id)
        if workspace is None:
            continue
        scopes.append(
            OutboxEventRlsScope(
                event_id=event.event_id,
                user_id=workspace.owner_user_id,
                workspace_id=workspace.id,
                project_id=project.id,
            )
        )
    return scopes


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
