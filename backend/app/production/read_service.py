"""Bounded production reads: aggregate in SQL, load history only on demand."""

from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime
from uuid import UUID

from sqlalchemy import SQLColumnExpression, String, and_, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.shot_pipeline import SHOT_NODES
from app.production.read_models import (
    ArtifactRead,
    ProductionArtifactPage,
    ProductionRunHistoryRead,
    ProductionRunPage,
    ProductionRunStatusRead,
    ProductionStageRead,
    ProductionSummaryRead,
)
from app.shared.errors import NotFoundError, ValidationAppError


def _encode_cursor(created_at: str, identity: UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at}/{identity}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        if len(cursor) > 256:
            raise ValueError("cursor too long")
        raw = base64.b64decode(cursor, altchars=b"-_", validate=True).decode()
        timestamp, identity = raw.split("/", 1)
        datetime.fromisoformat(timestamp)
        return timestamp, UUID(identity)
    except (ValueError, UnicodeError) as exc:
        raise ValidationAppError("Invalid production history cursor") from exc


def _before(
    created_at: SQLColumnExpression[datetime],
    identity: SQLColumnExpression[UUID],
    cursor: str,
    *,
    sqlite: bool,
) -> ColumnElement[bool]:
    timestamp, row_id = _decode_cursor(cursor)
    # SQLite server-default timestamps can omit fractional zeroes. Preserve
    # their exact storage text; DateTime binding would add .000000 and repeat
    # the entire second forever. PostgreSQL retains native timestamp comparison.
    bound = literal(timestamp, String()) if sqlite else literal(datetime.fromisoformat(timestamp))
    return or_(created_at < bound, and_(created_at == bound, identity < row_id))


def _run_columns() -> Select[tuple[object, ...]]:
    # Select individual columns, not NodeRun ORM rows: snapshots may contain
    # large frozen prompts/model manifests which a monitor must not load.
    return select(
        NodeRun.id,
        NodeRun.status,
        NodeRun.result_artifact_id,
        GraphNode.node_key,
        NodeRun.attempt_no,
        NodeRun.input_snapshot["shot_id"].as_string().label("shot_id"),
        func.coalesce(NodeRun.input_snapshot["execution_branch"].as_string(), "formal").label(
            "execution_branch"
        ),
        NodeRun.input_snapshot["experiment_id"].as_string().label("experiment_id"),
        NodeRun.created_at,
        cast(NodeRun.created_at, String).label("cursor_created_at"),
        NodeRun.error_code,
        func.substr(NodeRun.error_summary, 1, 500).label("error_summary"),
    ).join(GraphNode, GraphNode.id == NodeRun.graph_node_id)


class ProductionReadService:
    """Caller establishes authenticated workspace and project ownership first."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sqlite = session.get_bind().dialect.name == "sqlite"

    async def statuses(
        self,
        *,
        project_id: UUID,
        run_ids: list[UUID],
    ) -> list[ProductionRunStatusRead]:
        if not run_ids or len(run_ids) > 100:
            raise ValidationAppError("Request between 1 and 100 execution identities")
        rows = (
            (
                await self._session.execute(
                    select(
                        NodeRun.id,
                        NodeRun.status,
                        NodeRun.result_artifact_id,
                        NodeRun.error_code,
                    ).where(
                        NodeRun.project_id == project_id,
                        NodeRun.id.in_(run_ids),
                    )
                )
            )
            .mappings()
            .all()
        )
        by_id = {row["id"]: ProductionRunStatusRead.model_validate(dict(row)) for row in rows}
        if set(by_id) != set(run_ids):
            # Do not return partial successes or reveal which foreign identity exists.
            raise NotFoundError("Execution identity is missing or outside the project")
        return [by_id[run_id] for run_id in run_ids]

    async def summary(self, *, project_id: UUID) -> ProductionSummaryRead:
        shot = func.coalesce(NodeRun.input_snapshot["shot_id"].as_string(), "project")
        branch = func.coalesce(NodeRun.input_snapshot["execution_branch"].as_string(), "formal")
        experiment = func.coalesce(NodeRun.input_snapshot["experiment_id"].as_string(), "")
        ranked = (
            _run_columns()
            .add_columns(
                func.row_number()
                .over(
                    partition_by=(shot, GraphNode.node_key, branch, experiment),
                    order_by=(
                        NodeRun.attempt_no.desc(),
                        NodeRun.created_at.desc(),
                        NodeRun.id.desc(),
                    ),
                )
                .label("position")
            )
            .where(NodeRun.project_id == project_id)
            .subquery()
        )
        # One effective attempt per logical node, matching the existing monitor;
        # a failed old attempt must not outvote a newer successful attempt.
        # Group into a fixed number of canonical stage/status/mainline buckets.
        # Experiments remain in resource totals, but never complete a formal stage.
        canonical_stage = case((ranked.c.node_key.in_(SHOT_NODES), ranked.c.node_key), else_=None)
        mainline = and_(
            ranked.c.execution_branch == "formal",
            func.coalesce(ranked.c.experiment_id, "") == "",
        )
        count_rows = (
            (
                await self._session.execute(
                    select(ranked.c.status, canonical_stage, mainline, func.count())
                    .where(ranked.c.position == 1)
                    .group_by(ranked.c.status, canonical_stage, mainline)
                )
            )
            .tuples()
            .all()
        )
        counts: Counter[str] = Counter()
        stage_counts: dict[str, dict[str, int]] = {key: {} for key in SHOT_NODES}
        for status, key, is_mainline, count in count_rows:
            counts[status] += count
            if is_mainline and key is not None:
                stage_counts[key][status] = count

        # Independently retain one failure per stage: a busy failing stage must
        # not hide another stage's blocker behind the 20-row recent-history cap.
        stage_failures = (
            select(
                ranked,
                func.row_number()
                .over(
                    partition_by=ranked.c.node_key,
                    order_by=(ranked.c.created_at.desc(), ranked.c.id.desc()),
                )
                .label("stage_position"),
            )
            .where(
                ranked.c.position == 1,
                ranked.c.status == "failed",
                mainline,
                ranked.c.node_key.in_(SHOT_NODES),
            )
            .subquery()
        )
        stage_failure_rows = (
            (
                await self._session.execute(
                    select(stage_failures).where(stage_failures.c.stage_position == 1)
                )
            )
            .mappings()
            .all()
        )
        failure_by_stage = {
            row["node_key"]: ProductionRunHistoryRead.model_validate(dict(row))
            for row in stage_failure_rows
        }
        failures = (
            (
                await self._session.execute(
                    select(ranked)
                    .where(ranked.c.position == 1, ranked.c.status == "failed")
                    .order_by(ranked.c.created_at.desc(), ranked.c.id.desc())
                    .limit(20)
                )
            )
            .mappings()
            .all()
        )
        artifact_count = await self._session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.project_id == project_id)
        )
        return ProductionSummaryRead(
            project_id=project_id,
            total_runs=sum(counts.values()),
            completed_runs=sum(
                counts.get(status, 0)
                for status in ("completed", "cached", "completed_after_cancel", "approved")
            ),
            running_runs=sum(
                counts.get(status, 0)
                for status in ("queued", "running", "cancel_requested", "leased")
            ),
            failed_runs=counts.get("failed", 0),
            artifact_count=artifact_count or 0,
            recent_failures=[
                ProductionRunHistoryRead.model_validate(dict(row)) for row in failures
            ],
            has_more_failures=counts.get("failed", 0) > len(failures),
            stages=[
                ProductionStageRead(
                    node_key=key,
                    status_counts=stage_counts[key],
                    latest_failure=failure_by_stage.get(key),
                )
                for key in SHOT_NODES
            ],
        )

    async def runs(
        self,
        *,
        project_id: UUID,
        limit: int = 25,
        cursor: str | None = None,
    ) -> ProductionRunPage:
        if not 1 <= limit <= 100:
            raise ValidationAppError("History page size must be between 1 and 100")
        query = _run_columns().where(NodeRun.project_id == project_id)
        if cursor is not None:
            query = query.where(
                _before(NodeRun.created_at, NodeRun.id, cursor, sqlite=self._sqlite)
            )
        rows = (
            (
                await self._session.execute(
                    query.order_by(NodeRun.created_at.desc(), NodeRun.id.desc()).limit(limit + 1)
                )
            )
            .mappings()
            .all()
        )
        page = rows[:limit]
        return ProductionRunPage(
            items=[ProductionRunHistoryRead.model_validate(dict(row)) for row in page],
            next_cursor=(
                _encode_cursor(page[-1]["cursor_created_at"], page[-1]["id"])
                if len(rows) > limit
                else None
            ),
        )

    async def artifacts(
        self,
        *,
        project_id: UUID,
        limit: int = 25,
        cursor: str | None = None,
        usable_audio: bool = False,
    ) -> ProductionArtifactPage:
        if not 1 <= limit <= 100:
            raise ValidationAppError("History page size must be between 1 and 100")
        query = select(
            Artifact, cast(Artifact.created_at, String).label("cursor_created_at")
        ).where(Artifact.project_id == project_id)
        if usable_audio:
            query = query.where(
                Artifact.artifact_type == "audio",
                Artifact.mime_type.like("audio/%"),
                Artifact.storage_state == "available",
                Artifact.deleted_at.is_(None),
                Artifact.byte_size > 0,
                Artifact.object_key != "",
            )
        if cursor is not None:
            query = query.where(
                _before(Artifact.created_at, Artifact.id, cursor, sqlite=self._sqlite)
            )
        rows = list(
            await self._session.execute(
                query.order_by(Artifact.created_at.desc(), Artifact.id.desc()).limit(limit + 1)
            )
        )
        page = rows[:limit]
        return ProductionArtifactPage(
            items=[
                ArtifactRead(
                    id=a.id,
                    object_key=a.object_key,
                    content_hash=a.content_hash,
                    byte_size=a.byte_size,
                    mime_type=a.mime_type,
                    storage_state=a.storage_state,
                    produced_by_run_id=a.produced_by_run_id,
                    width=a.width,
                    height=a.height,
                    duration_seconds=str(a.duration_seconds)
                    if a.duration_seconds is not None
                    else None,
                )
                for a, _created_at in page
            ],
            next_cursor=(
                _encode_cursor(page[-1][1], page[-1][0].id) if len(rows) > limit else None
            ),
        )
