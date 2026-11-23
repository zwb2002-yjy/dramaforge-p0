"""OpenCut Timeline -> asynchronous Final Film Artifact production path.

The HTTP layer freezes one EditSession Timeline version and queues a project
scope NodeRun. The Worker resolves the frozen Formal references and performs
all media work through the Outbox -> Arq -> Worker boundary.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, ProjectCreativeProfile
from app.assets.models import Shot
from app.config import get_settings
from app.contracts.delivery_verification import BoundDeliveryOutput, DeliveryPlanRef
from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.editing.timeline_rules import clip_audio_volume
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.branches import branch_priority
from app.execution.experiment_nodes import queue_branch_nodes
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.command_models import ProductionCommandAuthorization
from app.production.delivery_graph import FINAL_FILM_FORMAT, FINAL_FILM_NODE, delivery_graph
from app.production.models import GraphVersion, ProductionGraph
from app.production.session_exports import timeline_hash as saved_timeline_hash
from app.providers.voice_config import freeze_project_voice
from app.runtime.scheduler import NodeRunScheduler
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    ProviderTaskPendingError,
    ValidationAppError,
)
from app.storage.materialized import MaterializedFile, MediaTransferError, materialize_stream
from app.storage.minio_store import ObjectStore
from app.storage.scratch import OwnedMediaDirectory

if TYPE_CHECKING:
    from app.execution.product_path import ExecuteNodeResult
    from app.production.timeline_renderer import TimelineRenderClip, TimelineRenderResult
    from app.storage.minio_store import StoredObject

_TAIL_NODE_KEYS = [
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
]
_DONE = frozenset({"completed", "cached", "completed_after_cancel"})
_PENDING = frozenset({"queued", "running", "cancel_requested"})
_FINAL_FILM_GRAPH_KEY = FINAL_FILM_NODE
_FINAL_FILM_FORMAT = FINAL_FILM_FORMAT
logger = logging.getLogger(__name__)
_MAX_FINAL_FILM_INPUT_BYTES = 8 * 1024 * 1024 * 1024
_MAX_INPUT_MEDIA_BYTES = 512 * 1024 * 1024


async def _cleanup_uploads(session: AsyncSession, *, run_id: UUID, store: ObjectStore) -> None:
    from app.production.final_film_uploads import cleanup_final_film_uploads
    from app.shared.observability import FINAL_FILM_CLEANUP_FAILURES

    try:
        await cleanup_final_film_uploads(session, node_run_id=run_id, store=store)
    except Exception:
        await session.rollback()
        FINAL_FILM_CLEANUP_FAILURES.inc()
        logger.warning("final_film_cleanup_deferred run=%s", run_id, exc_info=True)


class FinalFilmPrepareRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    timeline_version: int
    shot_ids: list[UUID]
    node_run_ids: list[UUID]
    preparation_fingerprint: str = Field(min_length=64, max_length=64)
    status: str = "queued"


class PreparationOperation(BaseModel):
    operation_key: str
    shot_id: UUID
    shot_number: int
    dialogue: str | None = None
    kind: str
    plan_fingerprint: str
    requires_provider: bool
    model_identity: dict[str, object] | None
    reason_code: str


class ReusedPreparation(BaseModel):
    shot_id: UUID
    kind: str
    node_run_id: UUID
    artifact_id: UUID | None


class FinalFilmPreparePreviewRead(BaseModel):
    project_id: UUID
    edit_session_id: UUID
    episode_id: UUID | None
    timeline_version: int
    timeline_hash: str
    preparation_fingerprint: str
    operations: list[PreparationOperation]
    reuse: list[ReusedPreparation]
    blockers: list[str]
    max_provider_operations: int
    max_external_model_operations: int


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FinalFilmRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    episode_id: UUID | None = None
    timeline_hash: str | None = None
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
    subtitle_artifact_id: UUID | None = None
    subtitle_content_hash: str | None = None
    subtitle_byte_size: int = 0
    subtitle_cue_count: int = 0


class FinalFilmJobRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    edit_session_id: UUID
    episode_id: UUID | None = None
    timeline_hash: str | None = None
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
    audio_volume: float
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
    draft_timeline: dict[str, Any] | None = None,
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
    raw_clips = (draft_timeline if draft_timeline is not None else row.timeline or {}).get("clips")
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
        if order < 1:
            raise ValidationAppError(
                "Timeline order must be a positive integer",
                details={"code": "INVALID_TIMELINE_ORDER", "clip_id": clip_id},
            )
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
        source_end = source_out if source_out is not None else source_in + duration
        if available > 0 and source_end > available + 0.05:
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
        audio_volume = clip_audio_volume(raw)
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
                audio_volume=audio_volume,
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
        if ref.shot_id not in seen:
            seen.add(ref.shot_id)
            shots.append(shot)
    return shots


async def _current_formal_tail_runs(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID
) -> dict[str, NodeRun]:
    rows = (
        (
            await session.execute(
                select(NodeRun, GraphNode.node_key)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.project_id == project_id,
                    NodeRun.input_snapshot["shot_id"].as_string() == str(shot_id),
                    GraphNode.node_key.in_(_TAIL_NODE_KEYS),
                )
                .order_by(NodeRun.created_at.desc(), NodeRun.attempt_no.desc(), NodeRun.id.desc())
            )
        )
        .tuples()
        .all()
    )
    selected: dict[str, NodeRun] = {}
    for run, key in rows:
        if branch_priority(run.input_snapshot, {"execution_branch": "formal"}) is not None:
            selected.setdefault(key, run)
    return selected


async def preview_formal_tail(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int | None,
) -> FinalFilmPreparePreviewRead:
    edit, refs = await _load_timeline_refs(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    if not refs:
        raise ValidationAppError("empty timeline", details={"code": "EMPTY_TIMELINE"})
    shots = await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    timeline_hash = saved_timeline_hash(edit.timeline)
    operations: list[PreparationOperation] = []
    reuse: list[ReusedPreparation] = []
    blockers: list[str] = []
    for shot in shots:
        speech_required = bool(shot.dialogue.strip()) and any(
            ref.shot_id == shot.id and not ref.raw_clip.get("muted") and not ref.audio_id
            for ref in refs
        )
        voice = (
            await freeze_project_voice(
                session,
                project_id=project_id,
                director_state=dict(shot.director_state or {}),
                silent=not speech_required,
            )
        ).model_dump(mode="json")
        runs = await _current_formal_tail_runs(session, project_id=project_id, shot_id=shot.id)
        prior = runs.get("voice")
        voice_changed = prior is None or (
            (prior.input_snapshot or {}).get("voice_execution") != voice
            or (prior.input_snapshot or {}).get("dialogue") != shot.dialogue.strip()
        )
        if prior is not None and voice_changed and prior.status in _PENDING:
            blockers.append("VOICE_PREVIOUS_RUN_PENDING")
        if prior is not None:
            uncertain = await session.scalar(
                select(ProviderOperation.id)
                .where(
                    ProviderOperation.node_run_id == prior.id,
                    ProviderOperation.status.in_(
                        ["submission_started", "unknown_submission", "submitted", "running"]
                    ),
                )
                .limit(1)
            )
            if uncertain is not None:
                blockers.append("VOICE_SUBMISSION_PENDING")
        for kind in _TAIL_NODE_KEYS:
            previous = runs.get(kind)
            new = previous is None or previous.status not in (_PENDING | _DONE)
            if kind in {"voice", "subtitle", "composite", "continuity_review"}:
                new = new or voice_changed
            if kind == "composite" and previous is not None:
                new = new or (previous.input_snapshot or {}).get("formal_video_artifact_id") != str(
                    shot.formal_video_artifact_id
                )
            if not new and previous is not None:
                reuse.append(
                    ReusedPreparation(
                        shot_id=shot.id,
                        kind=kind,
                        node_run_id=previous.id,
                        artifact_id=previous.result_artifact_id,
                    )
                )
                continue
            plan = _fingerprint(
                [
                    str(project_id),
                    str(edit.id),
                    edit.version,
                    timeline_hash,
                    str(shot.id),
                    str(shot.formal_video_artifact_id),
                    kind,
                    voice,
                    shot.dialogue.strip(),
                    str(previous.id) if previous else None,
                ]
            )
            external = kind == "voice" and voice.get("engine") == "voice_model"
            operations.append(
                PreparationOperation(
                    operation_key=f"final-film-prepare:{plan}",
                    shot_id=shot.id,
                    kind=kind,
                    shot_number=shot.shot_number,
                    dialogue=shot.dialogue.strip() if external else None,
                    plan_fingerprint=plan,
                    requires_provider=external,
                    model_identity=voice if kind == "voice" else None,
                    reason_code="PREPARATION_REQUIRED",
                )
            )
    fingerprint = _fingerprint(
        [
            str(edit.id),
            edit.version,
            timeline_hash,
            [item.operation_key for item in operations],
            [str(item.node_run_id) for item in reuse],
            blockers,
        ]
    )
    for operation in operations:
        operation.operation_key = (
            f"final-film-prepare:{_fingerprint([fingerprint, operation.plan_fingerprint])}"
        )
    return FinalFilmPreparePreviewRead(
        project_id=project_id,
        edit_session_id=edit.id,
        episode_id=edit.episode_id,
        timeline_version=edit.version,
        timeline_hash=timeline_hash,
        preparation_fingerprint=fingerprint,
        operations=operations,
        reuse=reuse,
        blockers=sorted(set(blockers)),
        max_provider_operations=sum(item.kind == "voice" for item in operations),
        max_external_model_operations=sum(item.requires_provider for item in operations),
    )


async def _locked_preparation(session: AsyncSession, project_id: UUID, session_id: UUID) -> None:
    await session.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    edit = await session.scalar(
        select(EditSession)
        .where(EditSession.id == session_id, EditSession.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if edit is None:
        raise NotFoundError("edit session not found")


async def approve_preparation(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int,
    actor_id: UUID,
    preparation_fingerprint: str,
    operation_keys: list[str],
) -> list[UUID]:
    """Called by the authenticated confirmation endpoint after the user selects operations."""
    await _locked_preparation(session, project_id, edit_session_id)
    if not operation_keys or len(set(operation_keys)) != len(operation_keys):
        raise ValidationAppError("confirmation must select distinct preview operations")
    existing = {
        g.command_key: g
        for g in await session.scalars(
            select(ProductionCommandAuthorization)
            .where(
                ProductionCommandAuthorization.project_id == project_id,
                ProductionCommandAuthorization.command_key.in_(operation_keys),
            )
            .execution_options(populate_existing=True)
        )
    }
    if len(existing) == len(operation_keys) and all(
        g.status == "accepted"
        and g.actor_id == actor_id
        and g.body.get("edit_session_id") == str(edit_session_id)
        and g.body.get("timeline_version") == expected_timeline_version
        and g.body.get("preparation_fingerprint") == preparation_fingerprint
        for g in existing.values()
    ):
        return [existing[key].id for key in operation_keys]
    preview = await preview_formal_tail(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    if preview.blockers or preview.preparation_fingerprint != preparation_fingerprint:
        raise ConflictError("preparation changed; review the preview again")
    offered = {op.operation_key: op for op in preview.operations}
    if (
        not operation_keys
        or len(set(operation_keys)) != len(operation_keys)
        or set(operation_keys) - offered.keys()
    ):
        raise ValidationAppError("confirmation must select distinct preview operations")
    profile = await session.scalar(
        select(ProjectCreativeProfile).where(ProjectCreativeProfile.project_id == project_id)
    )
    if profile is None:
        raise ValidationAppError("project profile missing")
    ids = []
    for key in operation_keys:
        operation = offered[key]
        body = {
            "edit_session_id": str(edit_session_id),
            "timeline_version": expected_timeline_version,
            "preparation_fingerprint": preparation_fingerprint,
            "operation": operation.model_dump(mode="json"),
            "reuse": [item.model_dump(mode="json") for item in preview.reuse],
        }
        grant = existing.get(key)
        if grant is None:
            grant = ProductionCommandAuthorization(
                project_id=project_id,
                actor_id=actor_id,
                shot_id=operation.shot_id,
                command_key=key,
                request_hash=_fingerprint(body),
                body=body,
                profile_version=profile.version,
                status="approved",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(grant)
            await session.flush()
        elif (
            grant.actor_id != actor_id
            or grant.request_hash != _fingerprint(body)
            or grant.status != "approved"
        ):
            raise ConflictError("the confirmed operation changed or is no longer available")
        ids.append(grant.id)
    await session.commit()
    return ids


async def prepare_formal_tail(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int,
    actor_id: UUID,
    preparation_fingerprint: str,
    command_authorization_ids: list[UUID],
) -> FinalFilmPrepareRead:
    await _locked_preparation(session, project_id, edit_session_id)
    grants = list(
        await session.scalars(
            select(ProductionCommandAuthorization)
            .where(
                ProductionCommandAuthorization.id.in_(command_authorization_ids),
                ProductionCommandAuthorization.project_id == project_id,
                ProductionCommandAuthorization.actor_id == actor_id,
            )
            .order_by(ProductionCommandAuthorization.command_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(grants) != len(command_authorization_ids) or any(
        grant.body.get("preparation_fingerprint") != preparation_fingerprint
        or grant.body.get("edit_session_id") != str(edit_session_id)
        or grant.body.get("timeline_version") != expected_timeline_version
        for grant in grants
    ):
        raise ConflictError("invalid preparation authorizations")

    def receipt(reuse: list[ReusedPreparation]) -> FinalFilmPrepareRead:
        run_ids = [g.node_run_id for g in grants if g.node_run_id]
        material_fingerprint = _fingerprint(
            [
                str(edit_session_id),
                expected_timeline_version,
                sorted(
                    [str(run_id) for run_id in run_ids] + [str(item.node_run_id) for item in reuse]
                ),
            ]
        )
        return FinalFilmPrepareRead(
            project_id=project_id,
            edit_session_id=edit_session_id,
            timeline_version=expected_timeline_version,
            shot_ids=list(
                dict.fromkeys(
                    [g.shot_id for g in grants if g.shot_id] + [item.shot_id for item in reuse]
                )
            ),
            node_run_ids=run_ids,
            preparation_fingerprint=material_fingerprint,
        )

    if grants and all(g.status == "accepted" for g in grants):
        original_reuse = grants[0].body.get("reuse")
        return receipt(
            [ReusedPreparation.model_validate(item) for item in original_reuse]
            if isinstance(original_reuse, list)
            else []
        )
    preview = await preview_formal_tail(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    required = {op.operation_key: op for op in preview.operations}
    if (
        preview.blockers
        or preview.preparation_fingerprint != preparation_fingerprint
        or required.keys() != {g.command_key for g in grants}
    ):
        raise ConflictError(
            "review and confirm the current preparation",
            details={"code": "PREPARATION_CONFIRMATION_REQUIRED"},
        )
    profile_version = await session.scalar(
        select(ProjectCreativeProfile.version).where(
            ProjectCreativeProfile.project_id == project_id
        )
    )
    for grant in grants:
        if (
            grant.status != "approved"
            or grant.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
            or grant.profile_version != profile_version
            or grant.request_hash != _fingerprint(grant.body)
            or grant.body.get("operation") != required[grant.command_key].model_dump(mode="json")
        ):
            raise ConflictError("expired, revoked or mismatched preparation authorization")
    by_key = {grant.command_key: grant for grant in grants}
    for op in preview.operations:
        shot = await session.get(Shot, op.shot_id)
        assert shot is not None
        runs = await queue_branch_nodes(
            session,
            project_id=project_id,
            shot_id=op.shot_id,
            user_id=actor_id,
            node_keys=[op.kind],
            force=True,
            include_missing_dependencies=False,
            voice_silent=bool(
                op.model_identity and op.model_identity.get("engine") == "pcm-silence"
            ),
            formal_video_artifact_id=shot.formal_video_artifact_id,
        )
        if len(runs) != 1:
            raise ConflictError("preparation did not produce the approved command")
        run = await session.get(NodeRun, runs[0])
        if op.kind == "voice" and (
            run is None or (run.input_snapshot or {}).get("voice_execution") != op.model_identity
        ):
            raise ConflictError("voice configuration changed during confirmation")
        grant = by_key[op.operation_key]
        grant.node_run_id = runs[0]
        grant.status = "accepted"
    result = receipt(preview.reuse)
    await session.commit()
    return result


async def _ensure_final_graph(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
) -> tuple[ProductionGraph, GraphNode, int]:
    graph, current = await delivery_graph(session, project_id=project_id, actor_id=actor_id)
    return graph, current.nodes[FINAL_FILM_NODE], current.version.version_number



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


def _snapshot_order(value: object, *, fallback: int) -> int:
    """Read a frozen clip order without silently renumbering it.

    The prepare step rejects ``order < 1``; a snapshot that still carries such a
    value (or a non-integer) is corrupt and must fail closed instead of being
    rewritten into a different edit.
    """
    if value is None:
        return fallback
    if isinstance(value, bool):
        raise ValidationAppError(
            "Final Film Timeline order is invalid",
            details={"code": "TIMELINE_SNAPSHOT_INVALID"},
        )
    if isinstance(value, int):
        order = value
    elif isinstance(value, float) and value.is_integer():
        order = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        order = int(value.strip())
    else:
        raise ValidationAppError(
            "Final Film Timeline order is invalid",
            details={"code": "TIMELINE_SNAPSHOT_INVALID"},
        )
    if order < 1:
        raise ValidationAppError(
            "Final Film Timeline order must be positive",
            details={"code": "TIMELINE_SNAPSHOT_INVALID"},
        )
    return order


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
                order=_snapshot_order(raw.get("order"), fallback=len(refs) + 1),
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
                audio_volume=clip_audio_volume(raw),
                raw_clip=raw,
            )
        )
    refs.sort(key=lambda ref: (ref.order, ref.clip_id))
    return refs


async def _read_artifact_file(
    artifacts: dict[UUID, Artifact],
    store: ObjectStore,
    artifact_id: UUID,
    *,
    project_id: UUID,
    artifact_type: str,
    directory: Path,
    cache: dict[UUID, MaterializedFile],
) -> tuple[Artifact, Path]:
    artifact = artifacts.get(artifact_id)
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
    if artifact_id in cache:
        return artifact, cache[artifact_id].path
    try:
        media = await materialize_stream(
            store.iter_bytes(object_key=artifact.object_key),
            destination=directory / f"artifact-{artifact_id}.media",
            max_bytes=_MAX_INPUT_MEDIA_BYTES,
            expected_size=artifact.byte_size,
            expected_hash=artifact.content_hash,
        )
    except MediaTransferError as exc:
        raise ValidationAppError(
            "Final Film input size/hash is invalid",
            details={"code": "FINAL_FILM_INPUT_HASH_MISMATCH", "artifact_id": str(artifact_id)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ValidationAppError(
            "Final Film input Artifact cannot be read",
            details={"code": "FINAL_FILM_INPUT_READ_FAILED", "artifact_id": str(artifact_id)},
        ) from exc
    cache[artifact_id] = media
    return artifact, media.path


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
    if (
        artifact is None
        or artifact.project_id != export.project_id
        or artifact.storage_state != "available"
    ):
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
    subtitle_item = next((item for item in items if item.role == "final_subtitle"), None)
    subtitle_artifact = (
        await session.get(Artifact, subtitle_item.source_artifact_id) if subtitle_item else None
    )
    declared_subtitle = manifest.get("subtitle_artifact_id")
    if declared_subtitle and (
        subtitle_item is None or str(subtitle_item.source_artifact_id) != declared_subtitle
    ):
        raise ValidationAppError(
            "Final Film subtitle linkage is missing",
            details={"code": "FINAL_SUBTITLE_UNAVAILABLE"},
        )
    if subtitle_item is not None and (
        subtitle_artifact is None
        or subtitle_artifact.project_id != export.project_id
        or subtitle_artifact.storage_state != "available"
        or subtitle_artifact.deleted_at is not None
        # Rendering the same frozen timeline twice produces identical bytes on
        # purpose, so a re-export reuses the earlier run's Artifact. Requiring
        # this run to own the bytes dropped the newest export out of history;
        # the declared content hash is what actually proves the linkage, and it
        # still fails closed when the Artifact carries different bytes.
        or subtitle_artifact.content_hash != manifest.get("subtitle_content_hash")
    ):
        raise ValidationAppError(
            "Final Film subtitles are not available",
            details={"code": "FINAL_SUBTITLE_UNAVAILABLE"},
        )
    return FinalFilmRead(
        subtitle_artifact_id=subtitle_artifact.id if subtitle_artifact else None,
        subtitle_content_hash=subtitle_artifact.content_hash if subtitle_artifact else None,
        subtitle_byte_size=int(subtitle_artifact.byte_size) if subtitle_artifact else 0,
        subtitle_cue_count=int(manifest.get("subtitle_cue_count", 0)),
        project_id=export.project_id,
        edit_session_id=edit_session.id,
        episode_id=export.episode_id,
        timeline_hash=export.timeline_hash,
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
        composite_artifact_ids=[
            str(item.source_artifact_id) for item in items if item.role == "shot_composite"
        ],
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
        episode_id=UUID(str(snapshot["episode_id"])) if snapshot.get("episode_id") else None,
        timeline_hash=str(snapshot["timeline_hash"]) if snapshot.get("timeline_hash") else None,
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


async def _assert_delivery_reviews(
    session: AsyncSession,
    *,
    project_id: UUID,
    refs: list[_TimelineRef],
) -> None:
    """Delivery admission: every clip's exact Artifact needs a human approval.

    A machine review that asked for a person, or a missing decision, blocks the
    render here instead of producing a film the user never approved. The check
    is about the frozen Timeline material, not about "current formal", so a
    later Shot edit cannot silently change what was approved.
    """
    from app.production.review_gate import evaluate_artifact_admission

    for ref in refs:
        admission = await evaluate_artifact_admission(
            session,
            project_id=project_id,
            shot_id=ref.shot_id,
            artifact_id=ref.artifact_id,
            stage="formal_video",
        )
        if admission.allowed:
            continue
        raise ValidationAppError(
            "a timeline clip has not been approved by a human review decision",
            details={
                "code": "DELIVERY_REVIEW_REQUIRED",
                "reason": admission.blocker or "REVIEW_DECISION_MISSING",
                "shot_id": str(ref.shot_id),
                "artifact_id": str(ref.artifact_id),
                "review_kind": admission.review_kind,
            },
        )


class TimelinePreviewClipRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str
    video_artifact_id: UUID
    start_ms: int
    end_ms: int
    source_in_ms: int
    source_out_ms: int
    duration_ms: int
    subtitle_text: str
    audio_artifact_id: UUID | None
    audio_state: Literal["available", "muted", "none", "unavailable"]
    audio_volume: float


class TimelinePreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    baseline_version: int
    draft_fingerprint: str
    duration_ms: int
    clips: list[TimelinePreviewClipRead]
    unsupported: list[str]


async def preview_timeline(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int,
    draft_timeline: dict[str, Any],
) -> TimelinePreviewRead:
    """Read-only draft instructions using the exact export reference and timing rules."""
    from app.production.timeline_subtitles import (
        TimelineClipInstructions,
        TimelineTimingError,
        build_timeline_subtitles,
        normalize_subtitle_text,
    )

    row, refs = await _load_timeline_refs(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
        draft_timeline=draft_timeline,
    )
    shots = {
        shot.id: shot
        for shot in await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    }
    instructions: list[TimelineClipInstructions] = []
    audio_states: list[Literal["available", "muted", "none", "unavailable"]] = []
    unsupported: list[str] = []
    for index, ref in enumerate(refs):
        if index > 0 and ref.transition_kind == "crossfade":
            unsupported.append("crossfade")
        audio_id = ref.audio_id
        audio_state: Literal["available", "muted", "none", "unavailable"] = "none"
        if bool(ref.raw_clip.get("muted")):
            audio_state = "muted"
            audio_id = None
        else:
            if audio_id is None:
                try:
                    composite, _artifact = await _latest_formal_composite(
                        session, project_id=project_id, ref=ref, shot=shots[ref.shot_id]
                    )
                    media = (composite.input_snapshot or {}).get("media_inputs")
                    voice = media.get("voice") if isinstance(media, dict) else None
                    if isinstance(voice, dict) and voice.get("artifact_id"):
                        audio_id = UUID(str(voice["artifact_id"]))
                except ValidationAppError as exc:
                    if exc.details.get("code") != "FORMAL_COMPOSITE_MISSING":
                        raise
                    if shots[ref.shot_id].dialogue:
                        audio_state = "unavailable"
            if audio_id is not None:
                artifact = await session.get(Artifact, audio_id)
                if (
                    artifact is None
                    or artifact.project_id != project_id
                    or artifact.artifact_type != "audio"
                    or artifact.storage_state != "available"
                    or artifact.deleted_at is not None
                ):
                    raise ValidationAppError(
                        "Timeline preview audio is not available in this project",
                        details={"code": "TIMELINE_AUDIO_SCOPE", "clip_id": ref.clip_id},
                    )
                audio_state = "available"
        if audio_state == "unavailable":
            unsupported.append("voice_unavailable")
        audio_states.append(audio_state)
        instructions.append(
            TimelineClipInstructions(
                clip_id=ref.clip_id,
                video_artifact_id=str(ref.artifact_id),
                subtitle_text=""
                if ref.subtitle_enabled is False
                else ref.subtitle
                if ref.subtitle is not None
                else shots[ref.shot_id].dialogue,
                source_in_seconds=ref.source_in_seconds,
                source_out_seconds=_number(
                    ref.raw_clip.get("source_out_seconds", ref.raw_clip.get("trim_end_seconds")),
                    default=None,
                    code="INVALID_TIMELINE_SOURCE_OUT",
                ),
                duration_seconds=ref.duration_seconds,
                transition_kind=ref.transition_kind,
                transition_duration_seconds=ref.transition_duration_seconds,
                audio_artifact_id=str(audio_id) if audio_id is not None else None,
                audio_volume=ref.audio_volume,
            )
        )
    metadata = draft_timeline.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("music_artifact_id"):
        unsupported.append("background_music")
    try:
        timing = build_timeline_subtitles(instructions)
    except TimelineTimingError as exc:
        raise ValidationAppError(str(exc), details={"code": "INVALID_TIMELINE_TIMING"}) from exc
    clips = [
        TimelinePreviewClipRead(
            clip_id=clip.clip_id,
            video_artifact_id=UUID(clip.video_artifact_id),
            start_ms=clock.start_ms,
            end_ms=clock.end_ms,
            source_in_ms=clock.source_in_ms,
            source_out_ms=clock.source_out_ms,
            duration_ms=clock.duration_ms,
            subtitle_text=normalize_subtitle_text(clip.subtitle_text),
            audio_artifact_id=UUID(clip.audio_artifact_id) if clip.audio_artifact_id else None,
            audio_state=audio_state,
            audio_volume=clip.audio_volume,
        )
        for clip, clock, audio_state in zip(instructions, timing.clips, audio_states, strict=True)
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            {"draft": draft_timeline, "clips": [clip.model_dump(mode="json") for clip in clips]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return TimelinePreviewRead(
        edit_session_id=row.id,
        baseline_version=row.version,
        draft_fingerprint=fingerprint,
        duration_ms=timing.duration_ms,
        clips=clips,
        unsupported=sorted(set(unsupported)),
    )


async def existing_bound_film(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    version: int,
    name: str,
    key: str,
    requested: DeliveryPlanRef,
) -> FinalFilmJobRead | None:
    """Re-read the exact frozen submission even after a plan stops accepting new exports."""
    run = await session.scalar(
        select(NodeRun)
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .where(
            NodeRun.project_id == project_id,
            GraphNode.node_key == FINAL_FILM_NODE,
            NodeRun.input_snapshot["idempotency_key"].as_string() == key,
        )
        .order_by(NodeRun.created_at.desc(), NodeRun.attempt_no.desc())
        .limit(1)
    )
    if run is None:
        return None
    snapshot = run.input_snapshot or {}
    scope = snapshot.get("delivery_output")
    if (
        not isinstance(scope, dict)
        or scope.get("plan_id") != str(requested.plan_id)
        or scope.get("master_run_id") != str(requested.master_run_id)
        or scope.get("control_epoch") != requested.control_epoch
        or snapshot.get("edit_session_id") != str(edit_session_id)
        or snapshot.get("timeline_version") != version
        or snapshot.get("name") != name
    ):
        raise ConflictError("此导出请求已绑定其他版本或计划")
    edit = await session.get(EditSession, edit_session_id)
    if edit is None or edit.project_id != project_id:
        raise NotFoundError("edit session not found")
    return await _job_read(session, run=run, edit_session=edit)


async def queue_final_film_render(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int,
    actor_id: UUID,
    idempotency_key: str | None,
    name: str,
    delivery_output: BoundDeliveryOutput | None = None,
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
    await _assert_delivery_reviews(session, project_id=project_id, refs=refs)
    metadata = (edit_session.timeline or {}).get("metadata")
    timeline: dict[str, Any] = {
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
    if delivery_output is not None:
        if delivery_output.project_id != project_id or edit_session.episode_id is None:
            raise ValidationAppError("只有当前项目的分集剪辑可用于分集交付槽")
        request_payload["delivery_output"] = delivery_output.model_dump(mode="json")
    request_fingerprint = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # The idempotency hash describes the user's saved Timeline, not a mutable
    # default. Freeze defaults separately so a same-key replay after a dialogue
    # edit restores the original queued result rather than inventing a new one.
    frozen_timeline = {
        **timeline,
        "clips": [
            {
                **clip,
                "subtitle": (
                    ""
                    if ref.subtitle_enabled is False
                    else ref.subtitle
                    if ref.subtitle is not None
                    else shots[ref.shot_id].dialogue
                ),
            }
            for clip, ref in zip(timeline["clips"], refs, strict=True)
        ],
    }
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
    _graph, node, _version = await _ensure_final_graph(
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
    # The key belongs to the project, including runs frozen on a prior graph version.
    matching = list(await session.scalars(
        select(NodeRun)
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .where(
            NodeRun.project_id == project_id, GraphNode.node_key == FINAL_FILM_NODE,
            NodeRun.input_snapshot["idempotency_key"].as_string() == external_key,
        )
        .order_by(NodeRun.created_at.desc(), NodeRun.attempt_no.desc())
    ))
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
    current_attempt = await session.scalar(
        select(func.max(NodeRun.attempt_no)).where(NodeRun.graph_node_id == node.id)
    )
    next_attempt = max(current_attempt or 0, max((r.attempt_no for r in matching), default=0)) + 1
    frozen_timeline_hash = saved_timeline_hash(edit_session.timeline)
    snapshot = {
        **request_payload,
        "node_key": _FINAL_FILM_GRAPH_KEY,
        "episode_id": str(edit_session.episode_id) if edit_session.episode_id else None,
        "timeline_hash": frozen_timeline_hash,
        "execution_path": "local-final-film-worker-v2",
        "source_commit": get_settings().source_commit,
        "idempotency_key": external_key,
        "request_fingerprint": request_fingerprint,
        "timeline": frozen_timeline,
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
        episode_id=edit_session.episode_id,
        timeline_hash=frozen_timeline_hash,
        node_run_id=run_id,
        attempt_no=attempt_no,
        status="queued",
        job_id=job,
    )


async def list_final_film_jobs(
    session: AsyncSession, *, project_id: UUID, edit_session_id: UUID
) -> list[FinalFilmJobRead]:
    """Read frozen render history, never prepare, render, retry or mutate media."""
    edit_session = await session.scalar(
        select(EditSession).where(
            EditSession.id == edit_session_id, EditSession.project_id == project_id
        )
    )
    if edit_session is None:
        raise NotFoundError("Final Film EditSession not found")
    runs = await session.scalars(
        select(NodeRun)
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .where(
            NodeRun.project_id == project_id,
            GraphNode.node_key == _FINAL_FILM_GRAPH_KEY,
            NodeRun.input_snapshot["edit_session_id"].as_string() == str(edit_session_id),
        )
        .order_by(NodeRun.created_at.desc(), NodeRun.id.desc())
    )
    results: list[FinalFilmJobRead] = []
    for run in runs:
        try:
            results.append(await _job_read(session, run=run, edit_session=edit_session))
        except ValidationAppError as exc:
            # An unavailable historical artifact must not hide the other exports.
            results.append(
                FinalFilmJobRead(
                    project_id=project_id,
                    edit_session_id=edit_session_id,
                    episode_id=UUID(str(run.input_snapshot["episode_id"]))
                    if run.input_snapshot.get("episode_id")
                    else None,
                    timeline_hash=str(run.input_snapshot["timeline_hash"])
                    if run.input_snapshot.get("timeline_hash")
                    else None,
                    timeline_version=int(
                        str((run.input_snapshot or {}).get("timeline_version") or 1)
                    ),
                    node_run_id=run.id,
                    attempt_no=run.attempt_no,
                    status=run.status,
                    error_code=str(exc.details.get("code", "FINAL_FILM_RESULT_UNAVAILABLE")),
                    error_summary=str(exc),
                )
            )
    return results


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


@dataclass(frozen=True)
class _RenderedFinalFilm:
    rendered: TimelineRenderResult
    formal_lineage: list[dict[str, Any]]
    duration: Decimal


async def _render_final_film_media(
    *,
    project_id: UUID,
    snapshot: dict[str, Any],
    resolved: list[tuple[_TimelineRef, NodeRun, Artifact, dict[str, Any]]],
    artifacts: dict[UUID, Artifact],
    obj_store: ObjectStore,
    directory: Path,
    metadata: Any,
    music_id: Any,
) -> _RenderedFinalFilm:
    """Materialize frozen inputs and render without opening a database transaction.

    The caller owns the scratch directory and closes metadata reads before entry.
    """
    from app.production.timeline_renderer import (
        TimelineRenderClip,
        TimelineRenderError,
        render_timeline,
    )

    media_cache: dict[UUID, MaterializedFile] = {}
    timeline_clips: list[TimelineRenderClip] = []
    formal_lineage: list[dict[str, Any]] = []
    frozen_references = snapshot.get("formal_references")
    frozen_dialogue = {
        str(item.get("clip_id")): str(item.get("dialogue") or "")
        for item in (frozen_references if isinstance(frozen_references, list) else [])
        if isinstance(item, dict)
    }
    for ref, composite_run, composite_artifact, media in resolved:
        _video_artifact, video_path = await _read_artifact_file(
            artifacts,
            obj_store,
            ref.artifact_id,
            project_id=project_id,
            artifact_type="video",
            directory=directory,
            cache=media_cache,
        )
        voice_input = media.get("voice")
        default_audio_id = (
            UUID(str(voice_input["artifact_id"]))
            if isinstance(voice_input, dict) and voice_input.get("artifact_id")
            else None
        )
        selected_audio_id = ref.audio_id or default_audio_id
        audio_path = None
        if selected_audio_id is not None and not bool(ref.raw_clip.get("muted")):
            _audio_artifact, audio_path = await _read_artifact_file(
                artifacts,
                obj_store,
                selected_audio_id,
                project_id=project_id,
                artifact_type="audio",
                directory=directory,
                cache=media_cache,
            )
        # Subtitle defaults were frozen at queue time. Empty/disabled text
        # must never resurrect a subsequently edited Canonical Shot dialogue.
        subtitle_text = (
            ""
            if ref.subtitle_enabled is False
            else ref.subtitle
            if ref.subtitle is not None
            else frozen_dialogue.get(ref.clip_id, "")
        )
        timeline_clips.append(
            TimelineRenderClip(
                clip_id=ref.clip_id,
                video_artifact_id=str(ref.artifact_id),
                video_path=video_path,
                audio_path=audio_path,
                subtitle_text=subtitle_text,
                source_in_seconds=ref.source_in_seconds,
                source_out_seconds=(
                    float(
                        str(
                            ref.raw_clip.get(
                                "source_out_seconds", ref.raw_clip.get("trim_end_seconds")
                            )
                        )
                    )
                    if ref.raw_clip.get("source_out_seconds", ref.raw_clip.get("trim_end_seconds"))
                    is not None
                    else None
                ),
                duration_seconds=ref.duration_seconds,
                transition_kind=ref.transition_kind,
                transition_duration_seconds=ref.transition_duration_seconds,
                audio_artifact_id=str(selected_audio_id) if selected_audio_id else None,
                audio_volume=ref.audio_volume,
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
    music_path = None
    if music_id:
        _music_artifact, music_path = await _read_artifact_file(
            artifacts,
            obj_store,
            UUID(str(music_id)),
            project_id=project_id,
            artifact_type="audio",
            directory=directory,
            cache=media_cache,
        )
    lineage = hashlib.sha256(
        json.dumps(formal_lineage, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        rendered = await render_timeline(
            timeline_clips,
            lineage=lineage,
            music_path=music_path,
            output_path=directory / "final.mp4",
            music_volume=(
                float(metadata.get("music_volume", 0.12)) if isinstance(metadata, dict) else 0.12
            ),
        )
    except TimelineRenderError as exc:
        raise ValidationAppError(str(exc), details={"code": "FINAL_FILM_RENDER_FAILED"}) from exc
    duration = _validate_final_film_media(rendered, timeline_clips)
    return _RenderedFinalFilm(rendered, formal_lineage, duration)


def _validate_final_film_media(
    rendered: TimelineRenderResult, timeline_clips: list[TimelineRenderClip]
) -> Decimal:
    """Require delivery media proof before any upload can begin."""
    probe = rendered.ffprobe
    streams = [item for item in probe.get("streams", []) if isinstance(item, dict)]
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    render_summary = dict(rendered.summary)
    measured_duration = float((probe.get("format") or {}).get("duration") or 0)
    planned_duration = float(render_summary.get("rendered_duration_seconds", 0))
    assertions = {
        "timeline_duration_matches": (
            planned_duration > 0
            and measured_duration + 0.001 >= planned_duration
            and abs(measured_duration - planned_duration) <= 0.15
        ),
        "mp4_container": "mp4" in str((probe.get("format") or {}).get("format_name") or ""),
        "h264_video": video.get("codec_name") == "h264",
        "aac_audio": audio.get("codec_name") == "aac",
        "dialogue_audio_present": any(clip.audio_path is not None for clip in timeline_clips)
        and bool(audio),
        "burned_subtitles": bool(render_summary.get("subtitle_burn_applied")),
        "subtitles_match_timeline": (
            int(render_summary.get("subtitle_cue_count", -1))
            == sum(bool(clip.subtitle_text.strip()) for clip in timeline_clips)
            and (
                not any(clip.subtitle_text.strip() for clip in timeline_clips)
                or bool(render_summary.get("subtitle_burn_applied"))
            )
        ),
        "timeline_edits_applied": render_summary.get("timeline_renderer") == "ffmpeg-v2",
    }
    required = {
        key: value
        for key, value in assertions.items()
        if key not in {"dialogue_audio_present", "burned_subtitles"}
    }
    if not all(required.values()):
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
    return duration


async def _stage_final_film_delivery(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    operation: ProviderOperation,
    edit_session_id: UUID,
    snapshot: dict[str, Any],
    media: _RenderedFinalFilm,
    stored: StoredObject,
    subtitle_stored: StoredObject | None,
) -> Artifact:
    """Stage the MP4/subtitle pair and export facts in the caller's transaction.

    The caller locks the active operation first and owns commit/rollback and
    upload-journal recovery. This function never uploads or commits.
    """
    formal_lineage, duration = media.formal_lineage, media.duration
    probe = media.rendered.ffprobe
    render_summary = dict(media.rendered.summary)
    video = next(
        (
            item
            for item in probe.get("streams", [])
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        {},
    )
    operation.request_summary = {**operation.request_summary, "uploads_finished": True}
    run.input_snapshot = {**snapshot, "formal_references": formal_lineage}
    artifact = await get_or_create_artifact(
        session,
        project_id=run.project_id,
        artifact_type="video",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
        # A Final Film is an assembly of an already-frozen timeline, not shot
        # media. Rendering the same saved version twice produces the same
        # bytes on purpose, and the product requires that re-export to return
        # the original result instead of failing; the shot-scoped rule that
        # forbids one NodeRun from claiming another's bytes does not apply.
        allow_cross_run_reuse=True,
    )
    subtitle_artifact = None
    if subtitle_stored is not None:
        subtitle_artifact = await get_or_create_artifact(
            session,
            project_id=run.project_id,
            artifact_type="subtitle",
            object_key=subtitle_stored.object_key,
            content_hash=subtitle_stored.content_hash,
            mime_type=subtitle_stored.mime_type,
            byte_size=subtitle_stored.byte_size,
            produced_by_run_id=run.id,
            # Same reasoning as the film bytes above: identical subtitles for
            # an unchanged timeline are the expected outcome of a re-export.
            allow_cross_run_reuse=True,
        )
    subtitle_delivery = {
        "subtitle_artifact_id": str(subtitle_artifact.id) if subtitle_artifact else None,
        "subtitle_content_hash": subtitle_artifact.content_hash if subtitle_artifact else None,
        "subtitle_byte_size": subtitle_artifact.byte_size if subtitle_artifact else 0,
        "subtitle_cue_count": int(render_summary.get("subtitle_cue_count", 0)),
    }
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
        episode_id=UUID(str(snapshot["episode_id"])) if snapshot.get("episode_id") else None,
        edit_session_id=edit_session_id,
        timeline_version=snapshot.get("timeline_version"),
        timeline_hash=snapshot.get("timeline_hash"),
        render_node_run_id=run.id,
        format=_FINAL_FILM_FORMAT,
        status="completed",
        requested_by=run.created_by,
        idempotency_key=str(snapshot.get("idempotency_key") or ""),
        manifest={
            "project_id": str(run.project_id),
            "edit_session_id": str(edit_session_id),
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
            **(
                {"delivery_output": snapshot["delivery_output"]}
                if "delivery_output" in snapshot else {}
            ),
            **subtitle_delivery,
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
    if subtitle_artifact is not None:
        session.add(
            ExportItem(
                export_id=export.id,
                ordinal=len(formal_lineage) + 1,
                source_artifact_id=subtitle_artifact.id,
                role="final_subtitle",
                metadata_json={
                    "timeline_version": snapshot.get("timeline_version"),
                    "node_run_id": str(run.id),
                    "mp4_artifact_id": str(artifact.id),
                    **subtitle_delivery,
                },
            )
        )
    return artifact


async def execute_final_film_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    obj_store: ObjectStore,
) -> ExecuteNodeResult:
    """Worker-only Final Film execution after NodeRun claim."""
    from app.execution.product_path import ExecuteNodeResult
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
    subtitle_stored = None
    delivery_committed = False
    uploads_finished = False
    run_id, operation_id = run.id, operation.id
    scratch = OwnedMediaDirectory(operation_id=run_id)
    directory = scratch.path
    try:
        # Resolve all immutable metadata in one short transaction. Reading an
        # Artifact lazily inside the media loop would reopen a transaction for
        # the entire download/render/upload interval.
        input_ids = {ref.artifact_id for ref, _, _, _ in resolved}
        for ref, _, _, media in resolved:
            voice = media.get("voice")
            audio_id = ref.audio_id or (
                UUID(str(voice["artifact_id"]))
                if isinstance(voice, dict) and voice.get("artifact_id")
                else None
            )
            if audio_id is not None and not bool(ref.raw_clip.get("muted")):
                input_ids.add(audio_id)
        timeline_snapshot = snapshot.get("timeline")
        metadata = timeline_snapshot.get("metadata") if isinstance(timeline_snapshot, dict) else {}
        music_id = metadata.get("music_artifact_id") if isinstance(metadata, dict) else None
        if music_id:
            input_ids.add(UUID(str(music_id)))
        artifacts = {
            artifact.id: artifact
            for artifact in (
                await session.scalars(
                    select(Artifact).where(
                        Artifact.id.in_(input_ids),
                        Artifact.project_id == run.project_id,
                    )
                )
            ).all()
        }
        await session.commit()
        if sum(artifact.byte_size for artifact in artifacts.values()) > _MAX_FINAL_FILM_INPUT_BYTES:
            raise ValidationAppError(
                "Final Film input exceeds the local resource limit",
                details={"code": "FINAL_FILM_INPUT_TOO_LARGE"},
            )
        film = await _render_final_film_media(
            project_id=run.project_id,
            snapshot=snapshot,
            resolved=resolved,
            artifacts=artifacts,
            obj_store=obj_store,
            directory=directory,
            metadata=metadata,
            music_id=music_id,
        )
        rendered = film.rendered
        # Persist the intended keys BEFORE the first upload. A process kill at
        # any upload boundary leaves a recoverable journal, including a failed
        # write that reached MinIO before raising locally.
        upload_prefix = f"projects/{run.project_id}/final-film/{run.id}/{uuid4()}"
        object_key = f"{upload_prefix}.mp4"
        subtitle_key = f"{upload_prefix}.srt"
        await set_node_run_rls_context(session, node_run_id=run_id)
        operation.request_summary = {
            **(operation.request_summary or {}),
            "upload_objects": [object_key] + ([subtitle_key] if rendered.subtitle_data else []),
            "uploads_finished": False,
        }
        await session.commit()
        stored = await obj_store.put_file(
            object_key=object_key,
            path=rendered.output_path,
            mime_type="video/mp4",
        )
        if rendered.subtitle_data:
            subtitle_stored = await obj_store.put_bytes(
                object_key=subtitle_key,
                data=rendered.subtitle_data,
                mime_type="application/x-subrip",
            )
        uploads_finished = True
        await set_node_run_rls_context(session, node_run_id=run_id)
        await session.refresh(operation, with_for_update=True)
        if operation.status != "submission_started":
            raise ValidationAppError(
                "Final Film attempt is no longer active",
                details={"code": "FINAL_FILM_ATTEMPT_EXPIRED"},
            )
        artifact = await _stage_final_film_delivery(
            session,
            run=run,
            node=node,
            operation=operation,
            edit_session_id=edit_session.id,
            snapshot=snapshot,
            media=film,
            stored=stored,
            subtitle_stored=subtitle_stored,
        )
        await session.commit()
        delivery_committed = True
        result = ExecuteNodeResult(
            node_run_id=run.id,
            artifact_id=artifact.id,
            object_key=artifact.object_key,
            content_hash=artifact.content_hash,
            byte_size=artifact.byte_size,
            identity_status=None,
            provider_operation_id=operation.id,
            node_type=node.node_type,
        )
        await _cleanup_uploads(session, run_id=run_id, store=obj_store)
        return result
    except Exception as exc:
        if delivery_committed:
            raise
        # Neither deliverable may become an available Artifact when the pair
        # failed before the Export transaction committed.
        await session.rollback()
        await set_node_run_rls_context(session, node_run_id=run_id)
        await session.refresh(run)
        operation = await session.get(ProviderOperation, operation_id, populate_existing=True)
        if operation is None:
            raise
        if uploads_finished:
            operation.request_summary = {**operation.request_summary, "uploads_finished": True}
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
        await _cleanup_uploads(session, run_id=run_id, store=obj_store)
        raise
    finally:
        scratch.cleanup()


__all__ = [
    "FinalFilmJobRead",
    "FinalFilmPrepareRead",
    "FinalFilmRead",
    "execute_final_film_node_run",
    "get_final_film_status",
    "prepare_formal_tail",
    "queue_final_film_render",
    "_load_timeline_refs",
]
