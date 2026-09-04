"""OpenCut Timeline -> asynchronous Final Film Artifact production path.

The HTTP layer freezes one EditSession Timeline version and queues a project
scope NodeRun. The Worker resolves the frozen Formal references and performs
all media work through the Outbox -> Arq -> Worker boundary.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Shot
from app.config import get_settings
from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.experiment_nodes import queue_branch_nodes
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.models import GraphVersion, ProductionGraph
from app.production.service import GraphService
from app.runtime.scheduler import NodeRunScheduler
from app.shared.errors import NotFoundError, ProviderTaskPendingError, ValidationAppError
from app.storage.minio_store import ObjectStore

if TYPE_CHECKING:
    from app.execution.product_path import ExecuteNodeResult

_TAIL_NODE_KEYS = [
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
]
_DONE = frozenset({"completed", "cached", "completed_after_cancel"})
_PENDING = frozenset({"queued", "running", "cancel_requested"})
_FINAL_FILM_GRAPH_KEY = "final_film_assembly"
_FINAL_FILM_FORMAT = "dramaforge-final-film-v1"


class FinalFilmPrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    expected_timeline_version: int = Field(ge=1)


class FinalFilmPrepareRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    timeline_version: int
    shot_ids: list[UUID]
    node_run_ids: list[UUID]
    status: str = "queued"


class FinalFilmRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    timeline_version: int
    export_id: UUID
    artifact_id: UUID
    node_run_id: UUID
    provider_operation_id: UUID
    format: str
    status: str
    duration_seconds: Decimal
    shot_count: int
    timeline_clip_count: int
    composite_artifact_ids: list[str]
    source_commit: str
    mime_type: str
    byte_size: int
    storage_state: str
    content_hash: str
    formal_references: list[dict[str, Any]]
    idempotency_key: str | None = None
    ffprobe: dict[str, Any] | None = None
    render_summary: dict[str, Any] | None = None


class FinalFilmJobRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    timeline_version: int
    node_run_id: UUID
    attempt_no: int
    status: str
    job_id: str | None = None
    export_id: UUID | None = None
    artifact_id: UUID | None = None
    error_code: str | None = None
    error_summary: str | None = None
    result: FinalFilmRead | None = None


@dataclass(frozen=True)
class _TimelineRef:
    clip_id: str
    shot_id: UUID
    artifact_id: UUID
    order: int
    source_in_seconds: float
    duration_seconds: float
    subtitle: str | None
    subtitle_enabled: bool | None
    audio_id: UUID | None
    transition_kind: str | None
    transition_duration_seconds: float
    raw_clip: dict[str, Any]


def _number(value: object, *, default: float | None, code: str) -> float | None:
    if value is None:
        return default
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(
            "Timeline numeric field is invalid", details={"code": code}
        ) from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValidationAppError("Timeline numeric field is not finite", details={"code": code})
    return result


def _transition(value: object) -> tuple[str | None, float]:
    if value is None:
        return None, 0.0
    if isinstance(value, str):
        kind = value.strip().lower()
        duration = 0.25 if kind == "crossfade" else 0.0
    elif isinstance(value, dict):
        kind = str(value.get("kind") or value.get("type") or "cut").strip().lower()
        duration = (
            _number(
                value.get("duration_seconds"),
                default=0.25 if kind == "crossfade" else 0.0,
                code="INVALID_TIMELINE_TRANSITION_DURATION",
            )
            or 0.0
        )
    else:
        raise ValidationAppError(
            "Timeline transition must be a string or object",
            details={"code": "INVALID_TIMELINE_TRANSITION"},
        )
    if kind not in {"cut", "crossfade"}:
        raise ValidationAppError(
            f"unsupported Timeline transition: {kind}",
            details={"code": "UNSUPPORTED_TIMELINE_TRANSITION"},
        )
    if duration < 0:
        raise ValidationAppError(
            "Timeline transition duration must be non-negative",
            details={"code": "INVALID_TIMELINE_TRANSITION_DURATION"},
        )
    return kind, duration


async def _project_or_404(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("project not found")
    return project


async def _load_timeline_refs(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int | None,
) -> tuple[EditSession, list[_TimelineRef]]:
    row = await session.scalar(
        select(EditSession).where(
            EditSession.id == edit_session_id,
            EditSession.project_id == project_id,
        )
    )
    if row is None:
        raise NotFoundError("edit session not found")
    if expected_timeline_version is not None and row.version != expected_timeline_version:
        raise ValidationAppError(
            "timeline version mismatch",
            details={
                "code": "TIMELINE_VERSION_MISMATCH",
                "expected": expected_timeline_version,
                "actual": row.version,
            },
        )
    raw_clips = (row.timeline or {}).get("clips")
    if not isinstance(raw_clips, list):
        raise ValidationAppError(
            "edit session timeline clips must be a list",
            details={"code": "INVALID_TIMELINE_CLIPS"},
        )
    refs: list[_TimelineRef] = []
    seen_clip_ids: set[str] = set()
    seen_orders: set[int] = set()
    for index, value in enumerate(raw_clips, start=1):
        if not isinstance(value, dict):
            raise ValidationAppError(
                "timeline clip must be an object",
                details={"code": "INVALID_TIMELINE_CLIP"},
            )
        raw = dict(value)
        clip_id = str(raw.get("id") or "")
        if not clip_id or clip_id in seen_clip_ids:
            raise ValidationAppError(
                "timeline clip ids must be unique and non-empty",
                details={"code": "INVALID_TIMELINE_CLIP_ID"},
            )
        try:
            shot_id = UUID(str(raw["shot_id"]))
            artifact_id = UUID(str(raw["artifact_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationAppError(
                "timeline clip requires valid shot_id and artifact_id",
                details={"code": "TIMELINE_REFERENCE_INVALID", "clip_id": clip_id},
            ) from exc
        artifact = await session.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.project_id != project_id
            or artifact.artifact_type != "video"
            or not artifact.mime_type.startswith("video/")
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
        ):
            raise ValidationAppError(
                "timeline reference is not an available project video Artifact",
                details={
                    "code": "TIMELINE_ARTIFACT_SCOPE",
                    "clip_id": clip_id,
                    "artifact_id": str(artifact_id),
                },
            )
        order_value = _number(raw.get("order"), default=float(index), code="INVALID_TIMELINE_ORDER")
        if order_value is None or not order_value.is_integer():
            raise ValidationAppError(
                "Timeline order must be an integer",
                details={"code": "INVALID_TIMELINE_ORDER", "clip_id": clip_id},
            )
        order = int(order_value)
        if order in seen_orders:
            raise ValidationAppError(
                "Timeline order values must be unique",
                details={"code": "DUPLICATE_TIMELINE_ORDER", "order": order},
            )
        source_in = (
            _number(
                raw.get("source_in_seconds", raw.get("trim_start_seconds")),
                default=0.0,
                code="INVALID_TIMELINE_SOURCE_IN",
            )
            or 0.0
        )
        source_out = _number(
            raw.get("source_out_seconds", raw.get("trim_end_seconds")),
            default=None,
            code="INVALID_TIMELINE_SOURCE_OUT",
        )
        duration = _number(
            raw.get("duration_seconds"),
            default=(source_out - source_in) if source_out is not None else None,
            code="INVALID_TIMELINE_DURATION",
        )
        if duration is None:
            duration = float(artifact.duration_seconds or 0)
        if source_in < 0 or duration <= 0 or (source_out is not None and source_out <= source_in):
            raise ValidationAppError(
                "Timeline trim/duration must be positive",
                details={"code": "INVALID_TIMELINE_TRIM", "clip_id": clip_id},
            )
        available = float(artifact.duration_seconds or 0)
        if available > 0 and source_in + duration > available + 0.05:
            raise ValidationAppError(
                "Timeline trim exceeds the Formal video Artifact",
                details={
                    "code": "TIMELINE_TRIM_OUT_OF_RANGE",
                    "clip_id": clip_id,
                    "source_in_seconds": source_in,
                    "duration_seconds": duration,
                    "artifact_duration_seconds": available,
                },
            )
        audio_id: UUID | None = None
        if raw.get("audio_id") not in {None, "", False}:
            try:
                audio_id = UUID(str(raw["audio_id"]))
            except (ValueError, TypeError) as exc:
                raise ValidationAppError(
                    "Timeline audio_id must be a UUID",
                    details={"code": "INVALID_TIMELINE_AUDIO_ID", "clip_id": clip_id},
                ) from exc
        transition_kind, transition_duration = _transition(raw.get("transition"))
        subtitle = raw.get("subtitle") if isinstance(raw.get("subtitle"), str) else None
        subtitle_enabled = raw.get("subtitle_enabled")
        if subtitle_enabled is not None and not isinstance(subtitle_enabled, bool):
            raise ValidationAppError(
                "Timeline subtitle_enabled must be boolean",
                details={"code": "INVALID_TIMELINE_SUBTITLE_FLAG", "clip_id": clip_id},
            )
        seen_clip_ids.add(clip_id)
        seen_orders.add(order)
        refs.append(
            _TimelineRef(
                clip_id=clip_id,
                shot_id=shot_id,
                artifact_id=artifact_id,
                order=order,
                source_in_seconds=source_in,
                duration_seconds=duration,
                subtitle=subtitle,
                subtitle_enabled=subtitle_enabled,
                audio_id=audio_id,
                transition_kind=transition_kind,
                transition_duration_seconds=transition_duration,
                raw_clip=raw,
            )
        )
    refs.sort(key=lambda ref: (ref.order, ref.clip_id))
    return row, refs


async def _formal_shots_for_refs(
    session: AsyncSession,
    *,
    project_id: UUID,
    refs: list[_TimelineRef],
) -> list[Shot]:
    shots: list[Shot] = []
    seen: set[UUID] = set()
    for ref in refs:
        if ref.shot_id in seen:
            continue
        shot = await session.get(Shot, ref.shot_id)
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError(
                "timeline shot does not belong to project",
                details={"code": "TIMELINE_SHOT_SCOPE", "shot_id": str(ref.shot_id)},
            )
        if shot.formal_video_artifact_id != ref.artifact_id:
            raise ValidationAppError(
                "timeline Formal video reference no longer matches Shot formal video",
                details={
                    "code": "FORMAL_REFERENCE_MISMATCH",
                    "shot_id": str(ref.shot_id),
                    "timeline_artifact": str(ref.artifact_id),
                    "shot_artifact": str(shot.formal_video_artifact_id)
                    if shot.formal_video_artifact_id
                    else None,
                },
            )
        seen.add(ref.shot_id)
        shots.append(shot)
    return shots


async def prepare_formal_tail(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int | None,
    actor_id: UUID,
) -> FinalFilmPrepareRead:
    await _project_or_404(session, project_id)
    edit_session, refs = await _load_timeline_refs(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    if not refs:
        raise ValidationAppError(
            "edit session timeline has no clips", details={"code": "EMPTY_TIMELINE"}
        )
    shots = await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    all_run_ids: list[UUID] = []
    for shot in shots:
        refresh_tail = False
        if shot.formal_composite_artifact_id is not None:
            composite_artifact = await session.get(Artifact, shot.formal_composite_artifact_id)
            composite_run = (
                await session.get(NodeRun, composite_artifact.produced_by_run_id)
                if composite_artifact is not None
                and composite_artifact.produced_by_run_id is not None
                else None
            )
            media_inputs = (
                (composite_run.input_snapshot or {}).get("media_inputs") if composite_run else None
            )
            video_input = media_inputs.get("video") if isinstance(media_inputs, dict) else None
            refresh_tail = not (
                isinstance(video_input, dict)
                and str(video_input.get("artifact_id")) == str(shot.formal_video_artifact_id)
            )
        run_ids = await queue_branch_nodes(
            session,
            project_id=project_id,
            shot_id=shot.id,
            user_id=actor_id,
            node_keys=list(_TAIL_NODE_KEYS),
            include_missing_dependencies=True,
            force=refresh_tail,
        )
        all_run_ids.extend(run_ids)
    await session.commit()
    return FinalFilmPrepareRead(
        project_id=project_id,
        edit_session_id=edit_session.id,
        timeline_version=edit_session.version,
        shot_ids=[ref.shot_id for ref in refs],
        node_run_ids=all_run_ids,
        status="queued",
    )


async def _ensure_final_graph(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
) -> tuple[ProductionGraph, GraphNode, int]:
    graphs = GraphService(session)
    existing = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project_id,
            ProductionGraph.scope_type == "project",
            ProductionGraph.scope_entity_id == project_id,
            ProductionGraph.template_key == "final-film-v1",
        )
    )
    if existing is not None and existing.current_version_id is not None:
        materialized = await graphs.materialize_definition(version_id=existing.current_version_id)
        return (
            existing,
            materialized.nodes[_FINAL_FILM_GRAPH_KEY],
            materialized.version.version_number,
        )
    graph = await graphs.create_graph(
        project_id=project_id,
        scope_type="project",
        scope_entity_id=project_id,
        template_key="final-film-v1",
        created_by=actor_id,
        definition={
            "nodes": [
                {
                    "key": _FINAL_FILM_GRAPH_KEY,
                    "type": "export",
                    "display_name": "Final Film Timeline Render",
                }
            ],
            "edges": [],
        },
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    node = materialized.nodes[_FINAL_FILM_GRAPH_KEY]
    if materialized.version.status == "draft":
        published = await graphs.publish(version_id=materialized.version.id, published_by=actor_id)
        return graph, node, published.version_number
    return graph, node, materialized.version.version_number


async def _latest_formal_composite(
    session: AsyncSession,
    *,
    project_id: UUID,
    ref: _TimelineRef,
    shot: Shot,
) -> tuple[NodeRun, Artifact]:
    rows = list(
        (
            await session.execute(
                select(NodeRun, Artifact, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .join(GraphVersion, GraphVersion.id == NodeRun.graph_version_id)
                .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
                .join(Artifact, Artifact.id == NodeRun.result_artifact_id)
                .where(NodeRun.project_id == project_id)
                .where(NodeRun.status.in_(_DONE))
                .where(GraphNode.node_key == "composite")
                .where(GraphNode.graph_version_id == NodeRun.graph_version_id)
                .where(ProductionGraph.project_id == project_id)
                .where(ProductionGraph.scope_type == "shot")
                .where(ProductionGraph.scope_entity_id == ref.shot_id)
            )
        )
        .tuples()
        .all()
    )
    candidates: list[tuple[NodeRun, Artifact]] = []
    for run, artifact, _node in rows:
        snapshot = run.input_snapshot or {}
        media = snapshot.get("media_inputs")
        video = media.get("video") if isinstance(media, dict) else None
        if (
            str(snapshot.get("shot_id")) != str(ref.shot_id)
            or snapshot.get("execution_branch") != "formal"
            or snapshot.get("experiment_id") is not None
            or run.result_artifact_id != artifact.id
            or (
                shot.formal_composite_artifact_id is not None
                and shot.formal_composite_artifact_id != artifact.id
            )
            or artifact.project_id != project_id
            or artifact.artifact_type != "video"
            or not artifact.mime_type.startswith("video/")
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
            or not isinstance(video, dict)
            or str(video.get("artifact_id")) != str(ref.artifact_id)
        ):
            continue
        formal_video = await session.get(Artifact, ref.artifact_id)
        if formal_video is None or video.get("content_hash") != formal_video.content_hash:
            continue
        if not isinstance(media, dict) or not all(
            isinstance(media.get(key), dict) for key in ("voice", "subtitle")
        ):
            continue
        candidates.append((run, artifact))
    if not candidates:
        raise ValidationAppError(
            f"no formal composite for timeline clip {ref.clip_id}",
            details={"code": "FORMAL_COMPOSITE_MISSING", "clip_id": ref.clip_id},
        )
    return max(
        candidates, key=lambda pair: (pair[0].attempt_no, pair[0].created_at, str(pair[0].id))
    )


def _snapshot_refs(snapshot: dict[str, object]) -> list[_TimelineRef]:
    timeline = snapshot.get("timeline")
    raw_clips = timeline.get("clips") if isinstance(timeline, dict) else None
    if not isinstance(raw_clips, list):
        raise ValidationAppError(
            "Final Film run has no frozen Timeline",
            details={"code": "TIMELINE_SNAPSHOT_MISSING"},
        )
    refs: list[_TimelineRef] = []
    for value in raw_clips:
        if not isinstance(value, dict):
            raise ValidationAppError(
                "Final Film run has an invalid Timeline clip",
                details={"code": "TIMELINE_SNAPSHOT_INVALID"},
            )
        raw = dict(value)
        try:
            clip_id = str(raw["id"])
            shot_id = UUID(str(raw["shot_id"]))
            artifact_id = UUID(str(raw["artifact_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationAppError(
                "Final Film Timeline reference is invalid",
                details={"code": "TIMELINE_SNAPSHOT_INVALID"},
            ) from exc
        transition_kind, transition_duration = _transition(raw.get("transition"))
        refs.append(
            _TimelineRef(
                clip_id=clip_id,
                shot_id=shot_id,
                artifact_id=artifact_id,
                order=int(raw.get("order") or len(refs) + 1),
                source_in_seconds=float(
                    raw.get("source_in_seconds") or raw.get("trim_start_seconds") or 0
                ),
                duration_seconds=float(raw.get("duration_seconds") or 0),
                subtitle=raw.get("subtitle") if isinstance(raw.get("subtitle"), str) else None,
                subtitle_enabled=raw.get("subtitle_enabled")
                if isinstance(raw.get("subtitle_enabled"), bool)
                else None,
                audio_id=UUID(str(raw["audio_id"]))
                if raw.get("audio_id") not in {None, "", False}
                else None,
                transition_kind=transition_kind,
                transition_duration_seconds=transition_duration,
                raw_clip=raw,
            )
        )
    refs.sort(key=lambda ref: (ref.order, ref.clip_id))
    return refs


async def _read_artifact_bytes(
    session: AsyncSession,
    store: ObjectStore,
    artifact_id: UUID,
    *,
    project_id: UUID,
    artifact_type: str,
) -> tuple[Artifact, bytes]:
    artifact = await session.get(Artifact, artifact_id)
    if (
        artifact is None
        or artifact.project_id != project_id
        or artifact.artifact_type != artifact_type
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
    ):
        raise ValidationAppError(
            "Final Film input Artifact is unavailable",
            details={"code": "FINAL_FILM_INPUT_UNAVAILABLE", "artifact_id": str(artifact_id)},
        )
    try:
        data = await store.get_bytes(object_key=artifact.object_key)
    except Exception as exc:  # noqa: BLE001
        raise ValidationAppError(
            "Final Film input Artifact cannot be read",
            details={"code": "FINAL_FILM_INPUT_READ_FAILED", "artifact_id": str(artifact_id)},
        ) from exc
    if not data or hashlib.sha256(data).hexdigest() != artifact.content_hash:
        raise ValidationAppError(
            "Final Film input Artifact hash mismatch",
            details={"code": "FINAL_FILM_INPUT_HASH_MISMATCH", "artifact_id": str(artifact_id)},
        )
    return artifact, data


async def _tail_for_ref(
    session: AsyncSession,
    *,
    project_id: UUID,
    ref: _TimelineRef,
    shot: Shot,
) -> tuple[NodeRun, Artifact]:
    try:
        return await _latest_formal_composite(session, project_id=project_id, ref=ref, shot=shot)
    except ValidationAppError as exc:
        if exc.details.get("code") != "FORMAL_COMPOSITE_MISSING":
            raise
        rows = list(
            (
                await session.execute(
                    select(NodeRun)
                    .where(NodeRun.project_id == project_id)
                    .where(NodeRun.input_snapshot["shot_id"].as_string() == str(ref.shot_id))
                    .where(NodeRun.input_snapshot["execution_branch"].as_string() == "formal")
                )
            )
            .scalars()
            .all()
        )
        tail_rows = [
            run
            for run in rows
            if str((run.input_snapshot or {}).get("node_key")) in set(_TAIL_NODE_KEYS)
        ]
        if any(run.status in _PENDING for run in tail_rows):
            raise ProviderTaskPendingError(
                "Final Film is waiting for the Formal Timeline tail"
            ) from None
        if tail_rows:
            raise
        raise ProviderTaskPendingError(
            "Final Film Formal Timeline tail has not been queued"
        ) from None


async def _export_for_run(
    session: AsyncSession, *, project_id: UUID, run_id: UUID
) -> Export | None:
    exports = list(
        (
            await session.execute(
                select(Export).where(
                    Export.project_id == project_id,
                    Export.format == _FINAL_FILM_FORMAT,
                )
            )
        )
        .scalars()
        .all()
    )
    return next(
        (item for item in exports if str((item.manifest or {}).get("node_run_id")) == str(run_id)),
        None,
    )


async def _final_film_read(
    session: AsyncSession,
    *,
    export: Export,
    edit_session: EditSession,
    refs: list[_TimelineRef],
) -> FinalFilmRead:
    artifact = await session.get(Artifact, export.result_artifact_id)
    if artifact is None or artifact.storage_state != "available":
        raise ValidationAppError(
            "Final Film Artifact is not available",
            details={"code": "FINAL_FILM_ARTIFACT_UNAVAILABLE"},
        )
    manifest: dict[str, Any] = dict(export.manifest or {})
    try:
        run_id = UUID(str(manifest["node_run_id"]))
        operation_id = UUID(str(manifest["provider_operation_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationAppError(
            "Final Film export is missing execution lineage",
            details={"code": "FINAL_FILM_LINEAGE_MISSING"},
        ) from exc
    items = list(
        (
            await session.execute(
                select(ExportItem)
                .where(ExportItem.export_id == export.id)
                .order_by(ExportItem.ordinal)
            )
        )
        .scalars()
        .all()
    )
    return FinalFilmRead(
        project_id=export.project_id,
        edit_session_id=edit_session.id,
        timeline_version=int(manifest.get("timeline_version") or edit_session.version),
        export_id=export.id,
        artifact_id=artifact.id,
        node_run_id=run_id,
        provider_operation_id=operation_id,
        format=export.format,
        status=export.status,
        duration_seconds=artifact.duration_seconds or Decimal("0"),
        shot_count=len({ref.shot_id for ref in refs}),
        timeline_clip_count=len(refs),
        composite_artifact_ids=[str(item.source_artifact_id) for item in items],
        source_commit=str(manifest.get("source_commit") or ""),
        mime_type=artifact.mime_type,
        byte_size=int(artifact.byte_size),
        storage_state=artifact.storage_state,
        content_hash=artifact.content_hash,
        formal_references=[
            item for item in manifest.get("formal_references", []) if isinstance(item, dict)
        ],
        idempotency_key=export.idempotency_key,
        ffprobe=manifest.get("ffprobe") if isinstance(manifest.get("ffprobe"), dict) else None,
        render_summary=(
            manifest.get("render_summary")
            if isinstance(manifest.get("render_summary"), dict)
            else None
        ),
    )


async def _job_read(
    session: AsyncSession, *, run: NodeRun, edit_session: EditSession
) -> FinalFilmJobRead:
    snapshot = dict(run.input_snapshot or {})
    refs = _snapshot_refs(snapshot)
    export = await _export_for_run(session, project_id=run.project_id, run_id=run.id)
    result = (
        await _final_film_read(session, export=export, edit_session=edit_session, refs=refs)
        if export is not None
        else None
    )
    return FinalFilmJobRead(
        project_id=run.project_id,
        edit_session_id=edit_session.id,
        timeline_version=int(cast(Any, snapshot.get("timeline_version")) or edit_session.version),
        node_run_id=run.id,
        attempt_no=run.attempt_no,
        status=run.status,
        export_id=export.id if export else None,
        artifact_id=export.result_artifact_id if export else None,
        error_code=run.error_code,
        error_summary=run.error_summary,
        result=result,
    )


async def queue_final_film_render(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int,
    actor_id: UUID,
    idempotency_key: str | None,
    name: str,
) -> FinalFilmJobRead:
    await _project_or_404(session, project_id)
    edit_session, refs = await _load_timeline_refs(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    if not refs:
        raise ValidationAppError("no timeline clips", details={"code": "EMPTY_TIMELINE"})
    shots = {
        shot.id: shot
        for shot in await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    }
    metadata = (edit_session.timeline or {}).get("metadata")
    timeline = {
        "version": edit_session.version,
        "clips": [
            {
                **ref.raw_clip,
                "id": ref.clip_id,
                "shot_id": str(ref.shot_id),
                "artifact_id": str(ref.artifact_id),
                "order": ref.order,
                "source_in_seconds": ref.source_in_seconds,
                "duration_seconds": ref.duration_seconds,
            }
            for ref in refs
        ],
        "metadata": dict(metadata) if isinstance(metadata, dict) else {},
    }
    request_payload = {
        "project_id": str(project_id),
        "edit_session_id": str(edit_session.id),
        "timeline_version": edit_session.version,
        "timeline": timeline,
        "name": name,
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    external_key = (
        idempotency_key.strip() if idempotency_key else f"auto-{request_fingerprint[:48]}"
    )
    if len(external_key) > 120:
        raise ValidationAppError(
            "Idempotency-Key is too long", details={"code": "IDEMPOTENCY_KEY_INVALID"}
        )
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        lock_seed = hashlib.sha256(
            f"final-film-idempotency:{project_id}:{external_key}".encode()
        ).hexdigest()
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_value)"),
            {"lock_value": int(lock_seed[:15], 16)},
        )
    graph, node, _version = await _ensure_final_graph(
        session, project_id=project_id, actor_id=actor_id
    )
    existing_exports = list(
        (
            await session.execute(
                select(Export).where(
                    Export.project_id == project_id,
                    Export.format == _FINAL_FILM_FORMAT,
                    Export.idempotency_key == external_key,
                )
            )
        )
        .scalars()
        .all()
    )
    for export in existing_exports:
        if str((export.manifest or {}).get("request_fingerprint") or "") != request_fingerprint:
            raise ValidationAppError(
                "Idempotency-Key was already used for a different Final Film request",
                details={"code": "IDEMPOTENCY_KEY_REUSED"},
            )
        raw_run_id = (export.manifest or {}).get("node_run_id")
        run = await session.get(NodeRun, UUID(str(raw_run_id))) if raw_run_id else None
        if run is None:
            raise ValidationAppError(
                "Final Film export is missing its NodeRun",
                details={"code": "FINAL_FILM_LINEAGE_MISSING"},
            )
        return await _job_read(session, run=run, edit_session=edit_session)
    runs = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id, NodeRun.graph_node_id == node.id)
                .order_by(NodeRun.attempt_no.desc(), NodeRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    matching = [
        run
        for run in runs
        if str((run.input_snapshot or {}).get("idempotency_key") or "") == external_key
    ]
    if any(
        str((run.input_snapshot or {}).get("request_fingerprint") or "") != request_fingerprint
        for run in matching
    ):
        raise ValidationAppError(
            "Idempotency-Key was already used for a different Final Film request",
            details={"code": "IDEMPOTENCY_KEY_REUSED"},
        )
    latest = matching[0] if matching else None
    if latest is not None and latest.status in {"queued", "running"}:
        return await _job_read(session, run=latest, edit_session=edit_session)
    next_attempt = max((int(run.attempt_no) for run in runs), default=0) + 1
    snapshot = {
        **request_payload,
        "node_key": _FINAL_FILM_GRAPH_KEY,
        "execution_path": "local-final-film-worker-v2",
        "source_commit": get_settings().source_commit,
        "idempotency_key": external_key,
        "request_fingerprint": request_fingerprint,
        "timeline": timeline,
        "formal_references": [
            {
                "clip_id": ref.clip_id,
                "shot_id": str(ref.shot_id),
                "formal_video_artifact_id": str(ref.artifact_id),
                "dialogue": shots[ref.shot_id].dialogue,
            }
            for ref in refs
        ],
        "retry_of_run_id": (
            str(latest.id) if latest is not None and latest.status == "failed" else None
        ),
    }
    run = NodeRun(
        project_id=project_id,
        graph_version_id=node.graph_version_id,
        graph_node_id=node.id,
        parent_run_id=latest.id if latest is not None and latest.status == "failed" else None,
        attempt_no=next_attempt,
        idempotency_key=(
            f"final-film:{hashlib.sha256(external_key.encode()).hexdigest()[:48]}:{next_attempt}"
        ),
        input_hash=request_fingerprint,
        status="queued",
        input_snapshot=snapshot,
        created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    run_id = run.id
    attempt_no = run.attempt_no
    job = await NodeRunScheduler(session).enqueue_node_run_only(run_id)
    return FinalFilmJobRead(
        project_id=project_id,
        edit_session_id=edit_session.id,
        timeline_version=edit_session.version,
        node_run_id=run_id,
        attempt_no=attempt_no,
        status="queued",
        job_id=job,
    )


async def get_final_film_status(
    session: AsyncSession,
    *,
    project_id: UUID,
    node_run_id: UUID,
) -> FinalFilmJobRead:
    run = await session.get(NodeRun, node_run_id)
    if run is None or run.project_id != project_id:
        raise NotFoundError("Final Film NodeRun not found")
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None or node.node_key != _FINAL_FILM_GRAPH_KEY:
        raise NotFoundError("Final Film NodeRun not found")
    edit_session_id = (run.input_snapshot or {}).get("edit_session_id")
    edit_session = (
        await session.get(EditSession, UUID(str(edit_session_id))) if edit_session_id else None
    )
    if edit_session is None:
        raise NotFoundError("Final Film EditSession not found")
    return await _job_read(session, run=run, edit_session=edit_session)


async def execute_final_film_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    obj_store: ObjectStore,
) -> ExecuteNodeResult:
    """Worker-only Final Film execution after NodeRun claim."""
    from app.execution.product_path import ExecuteNodeResult
    from app.production.timeline_renderer import (
        TimelineRenderClip,
        TimelineRenderError,
        render_timeline,
    )
    from app.shared.db import set_node_run_rls_context

    snapshot = dict(run.input_snapshot or {})
    refs = _snapshot_refs(snapshot)
    edit_session_id = snapshot.get("edit_session_id")
    edit_session = (
        await session.get(EditSession, UUID(str(edit_session_id))) if edit_session_id else None
    )
    if edit_session is None:
        raise ValidationAppError(
            "Final Film EditSession not found", details={"code": "FINAL_FILM_SESSION_MISSING"}
        )
    shots = {
        shot.id: shot
        for shot in await _formal_shots_for_refs(session, project_id=run.project_id, refs=refs)
    }
    resolved: list[tuple[_TimelineRef, NodeRun, Artifact, dict[str, Any]]] = []
    for ref in refs:
        composite_run, composite_artifact = await _tail_for_ref(
            session, project_id=run.project_id, ref=ref, shot=shots[ref.shot_id]
        )
        media = (composite_run.input_snapshot or {}).get("media_inputs")
        if not isinstance(media, dict):
            raise ProviderTaskPendingError("Final Film is waiting for composite media inputs")
        resolved.append((ref, composite_run, composite_artifact, media))
    operation = await session.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.node_run_id == run.id)
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    if operation is None:
        operation = ProviderOperation(
            node_run_id=run.id,
            attempt_no=run.attempt_no,
            purpose="primary",
            operation_kind="final_film.compose",
            actual_provider="local_ffmpeg",
            actual_model="ffmpeg-timeline-v2",
            request_fingerprint=run.input_hash,
            status="submission_started",
            request_summary={
                "execution_path": "local-final-film-worker-v2",
                "timeline_version": snapshot.get("timeline_version"),
            },
            response_summary={},
            submitted_at=datetime.now(UTC),
            provider_cost=Decimal("0"),
            currency="USD",
            execution_path_version="local-final-film-worker-v2",
        )
        session.add(operation)
    await session.flush()
    await session.commit()
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError(
            "Final Film ownership context unavailable",
            details={"code": "FINAL_FILM_RLS_CONTEXT_MISSING"},
        )
    stored = None
    try:
        timeline_clips: list[TimelineRenderClip] = []
        formal_lineage: list[dict[str, Any]] = []
        for ref, composite_run, composite_artifact, media in resolved:
            _video_artifact, video_bytes = await _read_artifact_bytes(
                session,
                obj_store,
                ref.artifact_id,
                project_id=run.project_id,
                artifact_type="video",
            )
            voice_input = media.get("voice")
            default_audio_id = (
                UUID(str(voice_input["artifact_id"]))
                if isinstance(voice_input, dict) and voice_input.get("artifact_id")
                else None
            )
            selected_audio_id = ref.audio_id or default_audio_id
            audio_bytes = None
            if selected_audio_id is not None and not bool(ref.raw_clip.get("muted")):
                _audio_artifact, audio_bytes = await _read_artifact_bytes(
                    session,
                    obj_store,
                    selected_audio_id,
                    project_id=run.project_id,
                    artifact_type="audio",
                )
            subtitle_text = (
                ""
                if ref.subtitle_enabled is False
                else (
                    ref.subtitle.strip()
                    if ref.subtitle and ref.subtitle.strip()
                    else shots[ref.shot_id].dialogue
                )
            )
            timeline_clips.append(
                TimelineRenderClip(
                    clip_id=ref.clip_id,
                    video_artifact_id=str(ref.artifact_id),
                    video_bytes=video_bytes,
                    audio_bytes=audio_bytes,
                    subtitle_text=subtitle_text,
                    source_in_seconds=ref.source_in_seconds,
                    duration_seconds=ref.duration_seconds,
                    transition_kind=ref.transition_kind,
                    transition_duration_seconds=ref.transition_duration_seconds,
                    audio_artifact_id=str(selected_audio_id) if selected_audio_id else None,
                )
            )
            formal_lineage.append(
                {
                    "clip_id": ref.clip_id,
                    "shot_id": str(ref.shot_id),
                    "formal_video_artifact_id": str(ref.artifact_id),
                    "composite_artifact_id": str(composite_artifact.id),
                    "composite_run_id": str(composite_run.id),
                    "media_inputs": media,
                    "timeline_edit": {
                        "source_in_seconds": ref.source_in_seconds,
                        "duration_seconds": ref.duration_seconds,
                        "subtitle": subtitle_text,
                        "audio_artifact_id": str(selected_audio_id) if selected_audio_id else None,
                        "transition": ref.transition_kind,
                        "transition_duration_seconds": ref.transition_duration_seconds,
                    },
                }
            )
        run.input_snapshot = {**snapshot, "formal_references": formal_lineage}
        timeline_snapshot = snapshot.get("timeline")
        metadata = timeline_snapshot.get("metadata") if isinstance(timeline_snapshot, dict) else {}
        music_id = metadata.get("music_artifact_id") if isinstance(metadata, dict) else None
        music_bytes = None
        if music_id:
            _music_artifact, music_bytes = await _read_artifact_bytes(
                session,
                obj_store,
                UUID(str(music_id)),
                project_id=run.project_id,
                artifact_type="audio",
            )
        lineage = hashlib.sha256(
            json.dumps(formal_lineage, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            rendered = await render_timeline(
                timeline_clips,
                lineage=lineage,
                music_bytes=music_bytes,
                music_volume=(
                    float(metadata.get("music_volume", 0.12))
                    if isinstance(metadata, dict)
                    else 0.12
                ),
            )
        except TimelineRenderError as exc:
            raise ValidationAppError(
                str(exc), details={"code": "FINAL_FILM_RENDER_FAILED"}
            ) from exc
        probe = rendered.ffprobe
        streams = [item for item in probe.get("streams", []) if isinstance(item, dict)]
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
        render_summary = dict(rendered.summary)
        assertions = {
            "mp4_container": "mp4" in str((probe.get("format") or {}).get("format_name") or ""),
            "h264_video": video.get("codec_name") == "h264",
            "aac_audio": audio.get("codec_name") == "aac",
            "dialogue_audio_present": any(bool(clip.audio_bytes) for clip in timeline_clips)
            and bool(audio),
            "burned_subtitles": all(clip.subtitle_text.strip() for clip in timeline_clips),
            "timeline_edits_applied": render_summary.get("timeline_renderer") == "ffmpeg-v2",
        }
        if not all(assertions.values()):
            raise ValidationAppError(
                "Final Film media proof is incomplete",
                details={
                    "code": "FINAL_FILM_MEDIA_ASSERTION_FAILED",
                    "assertions": assertions,
                },
            )
        probe["assertions"] = assertions
        duration = Decimal(str(float((probe.get("format") or {}).get("duration") or 0))).quantize(
            Decimal("0.001")
        )
        object_key = f"projects/{run.project_id}/final-film/{run.id}.mp4"
        stored = await obj_store.put_bytes(
            object_key=object_key,
            data=rendered.data,
            mime_type="video/mp4",
        )
        artifact = await get_or_create_artifact(
            session,
            project_id=run.project_id,
            artifact_type="video",
            object_key=stored.object_key,
            content_hash=stored.content_hash,
            mime_type=stored.mime_type,
            byte_size=stored.byte_size,
            produced_by_run_id=run.id,
        )
        artifact.duration_seconds = duration
        artifact.width = int(video["width"]) if video.get("width") else None
        artifact.height = int(video["height"]) if video.get("height") else None
        operation.status = "succeeded"
        operation.provider_cost = Decimal("0")
        operation.response_summary = {
            "ffprobe": probe,
            "timeline_render": render_summary,
            "duration_seconds": str(duration),
        }
        operation.completed_at = datetime.now(UTC)
        run.status = "completed"
        run.result_artifact_id = artifact.id
        run.provider_cost = Decimal("0")
        run.finished_at = datetime.now(UTC)
        run.output_summary = {
            "status": "completed",
            "artifact_id": str(artifact.id),
            "ffprobe": probe,
            "timeline_render": render_summary,
            "formal_references": formal_lineage,
        }
        node.latest_successful_run_id = run.id
        export = Export(
            project_id=run.project_id,
            format=_FINAL_FILM_FORMAT,
            status="completed",
            requested_by=run.created_by,
            idempotency_key=str(snapshot.get("idempotency_key") or ""),
            manifest={
                "project_id": str(run.project_id),
                "edit_session_id": str(edit_session.id),
                "timeline_version": snapshot.get("timeline_version"),
                "timeline": snapshot.get("timeline"),
                "request_fingerprint": run.input_hash,
                "formal_references": formal_lineage,
                "artifact_id": str(artifact.id),
                "node_run_id": str(run.id),
                "provider_operation_id": str(operation.id),
                "duration_seconds": str(duration),
                "source_commit": snapshot.get("source_commit"),
                "idempotency_key": snapshot.get("idempotency_key"),
                "ffprobe": probe,
                "render_summary": render_summary,
            },
            result_artifact_id=artifact.id,
            completed_at=datetime.now(UTC),
        )
        session.add(export)
        await session.flush()
        for ordinal, item in enumerate(formal_lineage, start=1):
            session.add(
                ExportItem(
                    export_id=export.id,
                    ordinal=ordinal,
                    source_artifact_id=UUID(str(item["composite_artifact_id"])),
                    role="shot_composite",
                    metadata_json=item,
                )
            )
        await session.commit()
        return ExecuteNodeResult(
            node_run_id=run.id,
            artifact_id=artifact.id,
            object_key=artifact.object_key,
            content_hash=artifact.content_hash,
            byte_size=artifact.byte_size,
            identity_status=None,
            provider_operation_id=operation.id,
            node_type=node.node_type,
        )
    except Exception as exc:
        if stored is not None:
            with suppress(Exception):
                await obj_store.delete_bytes(object_key=stored.object_key)
        operation.status = "failed"
        operation.error_code = (
            exc.details.get("code")
            if isinstance(exc, ValidationAppError)
            else "FINAL_FILM_RENDER_FAILED"
        )
        operation.error_summary = str(exc)[:500]
        operation.completed_at = datetime.now(UTC)
        run.status = "failed"
        run.error_code = operation.error_code
        run.error_summary = operation.error_summary
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise


__all__ = [
    "FinalFilmJobRead",
    "FinalFilmPrepareBody",
    "FinalFilmPrepareRead",
    "FinalFilmRead",
    "execute_final_film_node_run",
    "get_final_film_status",
    "prepare_formal_tail",
    "queue_final_film_render",
    "_load_timeline_refs",
]
