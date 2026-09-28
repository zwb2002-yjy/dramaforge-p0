"""Unified execution-trace query for Scene and Shot workbench aggregation.

``SceneWorkspaceService`` and ``ShotWorkbenchService`` used to scan
``NodeRun.input_snapshot["shot_id"]`` and rebuild the same trace read model
independently, which let the Scene view and Shot details drift apart. This
module owns that query: both callers now read one ``ShotExecutionTrace`` per
NodeRun.

The flag comes from stored facts: a ProviderOperation whose latest attempt is
``unknown_submission`` needs manual reconciliation, never a blind retry.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import NodeRun, ProviderOperation

UNKNOWN_SUBMISSION_STATUS = "unknown_submission"
DEFAULT_PER_SHOT_LIMIT = 20
_SCAN_LIMIT = 2000


class ShotExecutionTrace(BaseModel):
    """One NodeRun exactly as the Scene view and Shot details must show it."""

    model_config = ConfigDict(extra="forbid")

    node_run_id: UUID
    node_key: str | None
    status: str
    error_code: str | None
    error_summary: str | None
    finished_at: datetime | None
    result_artifact_id: UUID | None
    operation_outcome_unknown: bool


async def _unknown_submission_run_ids(
    session: AsyncSession, *, run_ids: list[UUID]
) -> set[UUID]:
    """Run ids whose latest ProviderOperation outcome is unknown."""
    if not run_ids:
        return set()
    latest_attempts = (
        await session.execute(
            select(
                ProviderOperation.node_run_id,
                func.max(ProviderOperation.attempt_no).label("attempt_no"),
            )
            .where(ProviderOperation.node_run_id.in_(run_ids))
            .group_by(ProviderOperation.node_run_id)
        )
    ).all()
    if not latest_attempts:
        return set()
    pairs = {(row.node_run_id, row.attempt_no) for row in latest_attempts}
    latest = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id.in_([pair[0] for pair in pairs])
            )
        )
    ).scalars().all()
    return {
        operation.node_run_id
        for operation in latest
        if operation.node_run_id is not None
        and (operation.node_run_id, operation.attempt_no) in pairs
        and operation.status == UNKNOWN_SUBMISSION_STATUS
    }


def _shot_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _node_key(raw: dict[str, object]) -> str | None:
    value = raw.get("node_key")
    return value if isinstance(value, str) else None


async def _load_traces(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_ids: set[UUID],
    per_shot_limit: int,
) -> dict[UUID, list[ShotExecutionTrace]]:
    rows = (
        await session.execute(
            select(NodeRun)
            .where(NodeRun.project_id == project_id)
            .order_by(NodeRun.created_at.desc())
            .limit(_SCAN_LIMIT)
        )
    ).scalars().all()
    selected: dict[UUID, list[tuple[NodeRun, dict[str, object]]]] = {
        shot_id: [] for shot_id in shot_ids
    }
    for run in rows:
        # Extract in Python from the JSON snapshot for portability.
        raw = dict(run.input_snapshot or {})
        shot_id = _shot_uuid(raw.get("shot_id"))
        if shot_id is None or shot_id not in selected:
            continue
        if len(selected[shot_id]) >= per_shot_limit:
            continue
        selected[shot_id].append((run, raw))
    unknown_outcomes = await _unknown_submission_run_ids(
        session,
        run_ids=[run.id for entries in selected.values() for run, _raw in entries],
    )
    return {
        shot_id: [
            ShotExecutionTrace(
                node_run_id=run.id,
                node_key=_node_key(raw),
                status=run.status,
                error_code=run.error_code,
                error_summary=run.error_summary,
                finished_at=run.finished_at,
                result_artifact_id=run.result_artifact_id,
                operation_outcome_unknown=run.id in unknown_outcomes,
            )
            for run, raw in entries
        ]
        for shot_id, entries in selected.items()
    }


async def load_shot_execution_traces(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    per_shot_limit: int = DEFAULT_PER_SHOT_LIMIT,
) -> list[ShotExecutionTrace]:
    """Most recent traces of one Shot, newest first."""
    traces = await _load_traces(
        session,
        project_id=project_id,
        shot_ids={shot_id},
        per_shot_limit=per_shot_limit,
    )
    return traces[shot_id]


async def load_scene_execution_traces(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_ids: list[UUID],
    per_shot_limit: int = DEFAULT_PER_SHOT_LIMIT,
) -> dict[UUID, list[ShotExecutionTrace]]:
    """Trace lists for every Shot of a Scene, keyed by Shot id."""
    return await _load_traces(
        session,
        project_id=project_id,
        shot_ids=set(shot_ids),
        per_shot_limit=per_shot_limit,
    )
