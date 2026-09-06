"""OpenCut adapter manifest for the project's formal production line."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.execution.branches import experiment_id as run_experiment_id
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation

router = APIRouter(tags=["opencut"], dependencies=[Depends(require_selected_workspace)])

_DONE = frozenset({"completed", "cached", "completed_after_cancel"})
_AVAILABLE_ARTIFACT_STATES = frozenset({"available", "stored"})


class OpenCutTrace(BaseModel):
    node_run_id: UUID | None = None
    artifact_id: UUID | None = None
    source_kind: str
    adopted_from_experiment_id: UUID | None = None
    provider_operation_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    reference_artifact_ids: list[UUID] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)
    effective_request: dict[str, object] = Field(default_factory=dict)


class OpenCutClip(BaseModel):
    id: str
    shot_id: UUID
    scene_id: UUID
    track_kind: str
    timeline_start_seconds: str
    timeline_end_seconds: str
    source_in_seconds: str = "0"
    duration_seconds: str
    artifact_id: UUID | None = None
    source_url: str | None = None
    mime_type: str | None = None
    text: str | None = None
    trace: OpenCutTrace


class OpenCutTrack(BaseModel):
    id: str
    kind: str
    name: str
    locked: bool = False
    muted: bool = False
    clips: list[OpenCutClip]


class OpenCutShot(BaseModel):
    shot_id: UUID
    shot_number: int
    scene_id: UUID
    timeline_start_seconds: str
    duration_seconds: str
    dialogue: str
    status: str
    artifact_ids: list[UUID]
    formal_artifacts: dict[str, UUID]


class OpenCutTimeline(BaseModel):
    duration_seconds: str
    frame_rate: int
    timebase: str
    aspect_ratio: str


class OpenCutManifest(BaseModel):
    schema_version: str
    adapter: str
    project_id: UUID
    official_line: str
    timeline: OpenCutTimeline
    tracks: list[OpenCutTrack]
    shots: list[OpenCutShot]


def _reference_artifact_ids(snapshot: dict[str, object]) -> list[UUID]:
    values: list[object] = []
    for key, value in snapshot.items():
        if key.endswith("_artifact_id") and key != "artifact_id":
            values.append(value)
    media_inputs = snapshot.get("media_inputs")
    if isinstance(media_inputs, dict):
        for item in media_inputs.values():
            if isinstance(item, dict):
                values.append(item.get("artifact_id"))
    result: list[UUID] = []
    for value in values:
        try:
            parsed = UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            continue
        if parsed not in result:
            result.append(parsed)
    return result


def _latest_formal_runs(
    rows: list[tuple[NodeRun, GraphNode]],
    *,
    shot_id: UUID,
) -> dict[str, NodeRun]:
    selected: dict[str, NodeRun] = {}
    for run, node in rows:
        snapshot = dict(run.input_snapshot or {})
        if str(snapshot.get("shot_id") or "") != str(shot_id):
            continue
        if run_experiment_id(snapshot) is not None:
            continue
        current = selected.get(node.node_key)
        if current is None or (
            run.attempt_no,
            run.created_at,
            str(run.id),
        ) > (
            current.attempt_no,
            current.created_at,
            str(current.id),
        ):
            selected[node.node_key] = run
    return selected


def _formal_video_run(
    rows: list[tuple[NodeRun, GraphNode]],
    *,
    shot_id: UUID,
    artifact_id: UUID,
) -> NodeRun | None:
    """Find the successful run that produced a Shot's formal video.

    The Shot pointer is the selection authority.  This lookup is only for
    production lineage (trace fields); it must never select a different or
    newer result when the pointer is present.  Experiment output is therefore
    valid here when it has explicitly been adopted into the formal pointer.
    """
    selected: NodeRun | None = None
    for run, node in rows:
        if (
            run.result_artifact_id != artifact_id
            or run.status not in _DONE
            or node.node_type != "video"
        ):
            continue
        snapshot = dict(run.input_snapshot or {})
        snapshot_shot_id = snapshot.get("shot_id")
        if snapshot_shot_id is not None and str(snapshot_shot_id) != str(shot_id):
            continue
        snapshot_stage = snapshot.get("stage")
        if snapshot_stage is not None and str(snapshot_stage) != "video":
            continue
        if selected is None or (
            run.attempt_no,
            run.created_at,
            str(run.id),
        ) > (
            selected.attempt_no,
            selected.created_at,
            str(selected.id),
        ):
            selected = run
    return selected


def _available_formal_video(
    artifact: Artifact | None,
    *,
    project_id: UUID,
) -> Artifact | None:
    """Return only a usable video artifact explicitly pointed to by a Shot."""
    if (
        artifact is None
        or artifact.project_id != project_id
        or artifact.artifact_type != "video"
        or artifact.storage_state not in _AVAILABLE_ARTIFACT_STATES
        or artifact.deleted_at is not None
    ):
        return None
    return artifact


async def _trace_for_run(
    *,
    project_id: UUID,
    run: NodeRun | None,
    artifact: Artifact | None,
    operation_by_run: dict[UUID, ProviderOperation],
) -> OpenCutTrace:
    if run is None:
        return OpenCutTrace(
            artifact_id=artifact.id if artifact is not None else None,
            source_kind="formal_artifact" if artifact is not None else "script",
        )
    snapshot = dict(run.input_snapshot or {})
    operation = operation_by_run.get(run.id)
    raw_experiment = snapshot.get("adopted_from_experiment_id")
    adopted_experiment: UUID | None = None
    if raw_experiment is not None:
        try:
            adopted_experiment = UUID(str(raw_experiment))
        except (TypeError, ValueError, AttributeError):
            adopted_experiment = None
    parameters: dict[str, object] = {}
    for key in ("model_profile", "selection_plan", "translation_report"):
        value = snapshot.get(key)
        if isinstance(value, dict):
            parameters[key] = value
    return OpenCutTrace(
        node_run_id=run.id,
        artifact_id=artifact.id if artifact is not None else None,
        source_kind="adopted_experiment" if adopted_experiment else "formal_run",
        adopted_from_experiment_id=adopted_experiment,
        provider_operation_id=operation.id if operation is not None else None,
        provider=operation.actual_provider if operation is not None else None,
        model=operation.actual_model if operation is not None else None,
        prompt=str(snapshot.get("prompt")) if snapshot.get("prompt") else None,
        reference_artifact_ids=_reference_artifact_ids(snapshot),
        parameters=parameters,
        effective_request=(
            dict(operation.request_summary or {}) if operation is not None else {}
        ),
    )


def _artifact_url(project_id: UUID, artifact: Artifact | None) -> str | None:
    if artifact is None:
        return None
    return f"/api/v1/projects/{project_id}/artifacts/{artifact.id}/content"


@router.get("/projects/{project_id}/opencut-manifest", response_model=OpenCutManifest)
async def opencut_manifest(
    project_id: UUID, user: CurrentUser, session: SessionDep
) -> OpenCutManifest:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    shots = (
        (
            await session.execute(
                select(Shot)
                .join(Scene, Scene.id == Shot.scene_id)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Shot.project_id == project_id)
                .where(Episode.project_id == project_id)
                .order_by(
                    Episode.episode_number,
                    Scene.scene_number,
                    Shot.sort_order,
                    Shot.shot_number,
                )
            )
        )
        .scalars()
        .all()
    )
    run_rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.project_id == project_id,
                    NodeRun.status.in_(_DONE),
                    NodeRun.result_artifact_id.is_not(None),
                )
            )
        )
        .tuples()
        .all()
    )
    run_ids = [run.id for run, _node in run_rows]
    operations = (
        list(
            (
                await session.execute(
                    select(ProviderOperation)
                    .where(ProviderOperation.node_run_id.in_(run_ids))
                    .order_by(
                        ProviderOperation.attempt_no,
                        ProviderOperation.created_at,
                    )
                )
            )
            .scalars()
            .all()
        )
        if run_ids
        else []
    )
    operation_by_run = {
        operation.node_run_id: operation
        for operation in operations
        if operation.node_run_id is not None
    }
    artifact_ids = {
        run.result_artifact_id
        for run, _node in run_rows
        if run.result_artifact_id is not None
    }
    artifact_ids.update(
        shot.formal_video_artifact_id
        for shot in shots
        if shot.formal_video_artifact_id is not None
    )
    artifacts = (
        list(
            (
                await session.execute(
                    select(Artifact).where(
                        Artifact.id.in_(artifact_ids),
                        Artifact.project_id == project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if artifact_ids
        else []
    )
    artifact_by_id = {artifact.id: artifact for artifact in artifacts}

    video_clips: list[OpenCutClip] = []
    audio_clips: list[OpenCutClip] = []
    subtitle_clips: list[OpenCutClip] = []
    shot_items: list[OpenCutShot] = []
    cursor = Decimal("0")
    for shot in shots:
        formal_runs = _latest_formal_runs(run_rows, shot_id=shot.id)
        video_artifact = _available_formal_video(
            artifact_by_id.get(shot.formal_video_artifact_id)
            if shot.formal_video_artifact_id is not None
            else None,
            project_id=project_id,
        )
        video_run = (
            _formal_video_run(
                run_rows,
                shot_id=shot.id,
                artifact_id=video_artifact.id,
            )
            if video_artifact is not None
            else None
        )
        # A pointer backed by execution lineage is only usable when that
        # lineage is a successful video run for this exact shot.  Hand-created
        # legacy formal rows without a produced-by pointer remain readable,
        # but a mismatched/cross-scope run fails closed.
        if (
            video_artifact is not None
            and video_artifact.produced_by_run_id is not None
            and video_run is None
        ):
            video_artifact = None
        # ``formal_artifacts`` deliberately reports only the selected formal
        # video.  Latest successful output and formal keyframes are not edit
        # timeline inputs; they remain available through their own workbench
        # surfaces.
        formal_artifacts = {"video": video_artifact.id} if video_artifact else {}
        formal_artifact_ids = [video_artifact.id] if video_artifact else []
        duration = Decimal(str(shot.duration_seconds))
        end = cursor + duration if video_artifact is not None else cursor
        shot_items.append(
            OpenCutShot(
                shot_id=shot.id,
                shot_number=shot.shot_number,
                scene_id=shot.scene_id,
                timeline_start_seconds=str(cursor),
                duration_seconds=str(duration),
                dialogue=shot.dialogue,
                status=shot.status,
                artifact_ids=formal_artifact_ids,
                formal_artifacts=formal_artifacts,
            )
        )

        if video_artifact is not None:
            video_clips.append(
                OpenCutClip(
                    id=f"video-{shot.id}",
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    track_kind="video",
                    timeline_start_seconds=str(cursor),
                    timeline_end_seconds=str(end),
                    duration_seconds=str(duration),
                    artifact_id=video_artifact.id,
                    source_url=_artifact_url(project_id, video_artifact),
                    mime_type=video_artifact.mime_type,
                    trace=await _trace_for_run(
                        project_id=project_id,
                        run=video_run,
                        artifact=video_artifact,
                        operation_by_run=operation_by_run,
                    ),
                )
            )

        # Audio/subtitle are auxiliary tracks for a formal video shot.  A shot
        # without a formal video is skipped from every edit track so a partial
        # project cannot look like a playable timeline.
        voice_run = formal_runs.get("voice") if video_artifact is not None else None
        voice_artifact = (
            artifact_by_id.get(voice_run.result_artifact_id)
            if voice_run is not None and voice_run.result_artifact_id is not None
            else None
        )
        if voice_run is not None and voice_artifact is not None:
            audio_clips.append(
                OpenCutClip(
                    id=f"audio-{shot.id}",
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    track_kind="audio",
                    timeline_start_seconds=str(cursor),
                    timeline_end_seconds=str(end),
                    duration_seconds=str(duration),
                    artifact_id=voice_artifact.id,
                    source_url=_artifact_url(project_id, voice_artifact),
                    mime_type=voice_artifact.mime_type,
                    trace=await _trace_for_run(
                        project_id=project_id,
                        run=voice_run,
                        artifact=voice_artifact,
                        operation_by_run=operation_by_run,
                    ),
                )
            )

        subtitle_run = formal_runs.get("subtitle") if video_artifact is not None else None
        subtitle_artifact = (
            artifact_by_id.get(subtitle_run.result_artifact_id)
            if subtitle_run is not None and subtitle_run.result_artifact_id is not None
            else None
        )
        if video_artifact is not None and (
            shot.dialogue or subtitle_artifact is not None
        ):
            subtitle_clips.append(
                OpenCutClip(
                    id=f"subtitle-{shot.id}",
                    shot_id=shot.id,
                    scene_id=shot.scene_id,
                    track_kind="subtitle",
                    timeline_start_seconds=str(cursor),
                    timeline_end_seconds=str(end),
                    duration_seconds=str(duration),
                    artifact_id=(subtitle_artifact.id if subtitle_artifact else None),
                    source_url=_artifact_url(project_id, subtitle_artifact),
                    mime_type=(subtitle_artifact.mime_type if subtitle_artifact else None),
                    text=shot.dialogue or None,
                    trace=await _trace_for_run(
                        project_id=project_id,
                        run=subtitle_run,
                        artifact=subtitle_artifact,
                        operation_by_run=operation_by_run,
                    ),
                )
            )
        cursor = end

    return OpenCutManifest(
        schema_version="opencut-manifest-v2",
        adapter="dramaforge-opencut-adapter-v1",
        project_id=project_id,
        official_line="formal",
        timeline=OpenCutTimeline(
            duration_seconds=str(cursor),
            frame_rate=24,
            timebase="1/24",
            aspect_ratio=project.aspect_ratio,
        ),
        tracks=[
            OpenCutTrack(id="video-main", kind="video", name="正式视频", clips=video_clips),
            OpenCutTrack(
                id="audio-dialogue",
                kind="audio",
                name="对白与声音",
                clips=audio_clips,
            ),
            OpenCutTrack(
                id="subtitle-main",
                kind="subtitle",
                name="字幕",
                clips=subtitle_clips,
            ),
        ],
        shots=shot_items,
    )
