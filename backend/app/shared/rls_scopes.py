"""Persisted ownership discovery for RLS-scoped requests and background work.

PostgreSQL discovery uses only the existing narrow SECURITY DEFINER functions.
The non-PostgreSQL paths retain the local/test ORM queries; they are never a
fallback for a failed PostgreSQL query. This module discovers scope, but never
opens a session or applies transaction settings. ``shared.db`` owns application
of the discovered scope and retains the public compatibility imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause


@dataclass(frozen=True)
class NodeRunRlsScope:
    """Ownership context reconstructed from NodeRun -> Project -> Workspace."""

    user_id: UUID
    workspace_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class ArtifactRlsScope:
    """Ownership context reconstructed from Artifact -> Project -> Workspace."""

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


@dataclass(frozen=True)
class DirectorTurnRlsScope:
    """Ownership context reconstructed for one recoverable Director turn."""

    user_id: UUID
    workspace_id: UUID
    project_id: UUID


def _owner_scope[OwnerScope: (NodeRunRlsScope, ArtifactRlsScope, DirectorTurnRlsScope)](
    scope_type: type[OwnerScope], row: RowMapping
) -> OwnerScope:
    """Map the fixed ownership columns returned by the trusted DB resolvers."""
    return scope_type(
        user_id=row["owner_user_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
    )


async def _resolve_postgresql_scope[
    OwnerScope: (NodeRunRlsScope, ArtifactRlsScope, DirectorTurnRlsScope)
](
    session: AsyncSession,
    statement: TextClause,
    parameters: dict[str, Any],
    scope_type: type[OwnerScope],
) -> OwnerScope | None:
    # Keep cardinality enforcement: duplicate ownership is an error, not a choice.
    result = await session.execute(statement, parameters)
    row = result.mappings().one_or_none()
    return None if row is None else _owner_scope(scope_type, row)


async def _list_postgresql_scopes[
    OwnerScope: (NodeRunRlsScope, ArtifactRlsScope, DirectorTurnRlsScope)
](
    session: AsyncSession,
    statement: TextClause,
    parameters: dict[str, Any],
    scope_type: type[OwnerScope],
    id_column: str,
) -> list[tuple[UUID, OwnerScope]]:
    # SQL stays literal at each entrypoint; id_column only addresses result rows.
    result = await session.execute(statement, parameters)
    return [(row[id_column], _owner_scope(scope_type, row)) for row in result.mappings().all()]


async def _project_scope[OwnerScope: (NodeRunRlsScope, ArtifactRlsScope, DirectorTurnRlsScope)](
    session: AsyncSession,
    project_id: UUID,
    scope_type: type[OwnerScope],
) -> OwnerScope | None:
    """Resolve the complete persisted owner chain for the non-PostgreSQL path."""
    from app.access.models import Project, Workspace

    project = await session.get(Project, project_id)
    if project is None:
        return None
    workspace = await session.get(Workspace, project.workspace_id)
    if workspace is None:
        return None
    return scope_type(
        user_id=workspace.owner_user_id,
        workspace_id=workspace.id,
        project_id=project.id,
    )


async def resolve_node_run_rls_scope(
    session: AsyncSession,
    *,
    node_run_id: UUID,
) -> NodeRunRlsScope | None:
    """Resolve worker ownership from persisted records, never queue payloads."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _resolve_postgresql_scope(
            session,
            text(
                """
                SELECT owner_user_id, workspace_id, project_id
                FROM app.node_run_context(:node_run_id)
                """
            ),
            {"node_run_id": node_run_id},
            NodeRunRlsScope,
        )

    from app.execution.models import NodeRun

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        return None
    return await _project_scope(session, run.project_id, NodeRunRlsScope)


async def resolve_artifact_rls_scope(
    session: AsyncSession,
    *,
    artifact_id: UUID,
) -> ArtifactRlsScope | None:
    """Resolve an Artifact's owner scope without weakening project RLS."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _resolve_postgresql_scope(
            session,
            text(
                """
                SELECT owner_user_id, workspace_id, project_id
                FROM app.artifact_context(:artifact_id)
                """
            ),
            {"artifact_id": artifact_id},
            ArtifactRlsScope,
        )

    from app.execution.models import Artifact

    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        return None
    return await _project_scope(session, artifact.project_id, ArtifactRlsScope)


async def list_queued_node_run_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    project_id: UUID | None = None,
    source_commit: str | None = None,
) -> list[tuple[UUID, NodeRunRlsScope]]:
    """Find queued work and ownership through the narrowly scoped DB resolver.

    Formal stacks bind a source commit at process start. Filtering by that
    value prevents a new commit-scoped Arq queue from replaying queued work
    that was created by an older runtime.
    """
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _list_postgresql_scopes(
            session,
            text(
                """
                SELECT node_run_id, owner_user_id, workspace_id, project_id
                FROM app.queued_node_run_contexts(:limit, :project_id, :source_commit)
                """
            ),
            {
                "limit": limit,
                "project_id": project_id,
                "source_commit": source_commit,
            },
            NodeRunRlsScope,
            "node_run_id",
        )

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
    if source_commit is not None:
        stmt = stmt.where(NodeRun.input_snapshot["source_commit"].as_string() == source_commit)
    result = await session.execute(stmt)
    scopes: list[tuple[UUID, NodeRunRlsScope]] = []
    for node_run_id in result.scalars().all():
        scope = await resolve_node_run_rls_scope(session, node_run_id=node_run_id)
        if scope is not None:
            scopes.append((node_run_id, scope))
    return scopes


async def list_resumable_provider_node_run_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    source_commit: str | None = None,
) -> list[tuple[UUID, NodeRunRlsScope]]:
    """Find interrupted Unified polls without exposing unrelated runtime rows."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _list_postgresql_scopes(
            session,
            text(
                """
                SELECT node_run_id, owner_user_id, workspace_id, project_id
                FROM app.resumable_provider_node_run_contexts(:limit, :source_commit)
                """
            ),
            {"limit": limit, "source_commit": source_commit},
            NodeRunRlsScope,
            "node_run_id",
        )

    from datetime import UTC, datetime, timedelta

    from app.execution.models import NodeRun, ProviderOperation

    stmt = (
        select(NodeRun.id)
        .join(ProviderOperation, ProviderOperation.node_run_id == NodeRun.id)
        .where(
            NodeRun.status.in_({"running", "cancel_requested"}),
            ProviderOperation.execution_path_version == "unified-v1",
            or_(
                ProviderOperation.status.in_(
                    {"submitted", "running", "timed_out", "cancel_requested"}
                )
                & ProviderOperation.provider_operation_id.is_not(None),
                (ProviderOperation.status == "submission_started")
                & ProviderOperation.provider_operation_id.is_(None)
                & (ProviderOperation.created_at < datetime.now(UTC) - timedelta(minutes=30)),
            ),
        )
        .distinct()
        .order_by(NodeRun.id)
        .limit(limit)
    )
    if source_commit is not None:
        stmt = stmt.where(NodeRun.input_snapshot["source_commit"].as_string() == source_commit)
    scopes: list[tuple[UUID, NodeRunRlsScope]] = []
    for node_run_id in (await session.execute(stmt)).scalars().all():
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


async def list_recoverable_director_turn_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    stale_before: datetime | None = None,
) -> list[tuple[UUID, DirectorTurnRlsScope]]:
    """Find stale interrupted/expired turns without trusting queue payloads."""

    cutoff = stale_before or datetime.now(UTC) - timedelta(minutes=15)
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _list_postgresql_scopes(
            session,
            text(
                """
                SELECT turn_id, owner_user_id, workspace_id, project_id
                FROM app.recoverable_director_turn_contexts(:limit, :stale_before)
                """
            ),
            {"limit": limit, "stale_before": cutoff},
            DirectorTurnRlsScope,
            "turn_id",
        )

    from app.director.turn_models import DirectorTurn

    rows = await session.execute(
        select(DirectorTurn.id, DirectorTurn.project_id)
        .where(
            DirectorTurn.status.in_({"queued", "thinking", "awaiting_user", "awaiting_execution"}),
            or_(
                DirectorTurn.deadline <= datetime.now(UTC),
                (
                    (DirectorTurn.status == "thinking")
                    & (DirectorTurn.transport_status == "submission_started")
                    & (DirectorTurn.updated_at < cutoff)
                ),
            ),
        )
        .order_by(DirectorTurn.updated_at, DirectorTurn.id)
        .limit(limit)
    )
    scopes: list[tuple[UUID, DirectorTurnRlsScope]] = []
    for turn_id, project_id in rows.tuples().all():
        scope = await _project_scope(session, project_id, DirectorTurnRlsScope)
        if scope is not None:
            scopes.append((turn_id, scope))
    return scopes


async def list_reconcilable_director_turn_rls_scopes(
    session: AsyncSession,
    *,
    limit: int,
    after_turn_id: UUID | None = None,
) -> list[tuple[UUID, DirectorTurnRlsScope]]:
    """Find turns whose current Proposal/NodeRun facts may advance a checkpoint."""

    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return await _list_postgresql_scopes(
            session,
            text(
                """
                SELECT turn_id, owner_user_id, workspace_id, project_id
                FROM app.reconcilable_director_turn_contexts(:limit, :after_turn_id)
                """
            ),
            {"limit": limit, "after_turn_id": after_turn_id},
            DirectorTurnRlsScope,
            "turn_id",
        )

    from app.director.turn_models import DirectorTurn

    rows = await session.execute(
        select(DirectorTurn.id, DirectorTurn.project_id)
        .where(
            or_(
                DirectorTurn.status == "awaiting_execution",
                (DirectorTurn.status == "awaiting_user")
                & or_(DirectorTurn.proposal_id.is_not(None), DirectorTurn.node_run_ids != []),
            )
        )
        .where(
            DirectorTurn.id > after_turn_id
            if after_turn_id is not None
            else DirectorTurn.id.is_not(None)
        )
        .order_by(DirectorTurn.id)
        .limit(limit)
    )
    scopes: list[tuple[UUID, DirectorTurnRlsScope]] = []
    for turn_id, project_id in rows.tuples().all():
        scope = await _project_scope(session, project_id, DirectorTurnRlsScope)
        if scope is not None:
            scopes.append((turn_id, scope))
    return scopes
