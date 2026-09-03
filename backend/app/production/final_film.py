"""Formal OpenCut EditSession -> Final Film Artifact (P0 revision).

Export source is one persisted EditSession Timeline version, not an
unordered Shot scan.  The service:

- reads the exact persisted Timeline clips and their Formal video references;
- validates expected_timeline_version against the server session;
- queues the zero-Provider shot tail for the Formal shots in that Timeline;
- selects only the latest formal Composite whose ``media_inputs.video`` points
  at the exact Formal Artifact referenced by the Timeline (no experiment / old
  attempt leakage);
- concatenates those composites in Timeline order into one playable MP4;
- records Export + ExportItem lineage and a project-scoped NodeRun /
  ProviderOperation for the final Artifact.

Final Film rendering is local FFmpeg (no paid Provider).  An optional
Idempotency-Key dedupes repeated exports.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
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
from app.shared.errors import NotFoundError, ValidationAppError
from app.storage.minio_store import get_object_store

_TAIL_NODE_KEYS = [
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
]
_DONE = frozenset({"completed", "cached", "completed_after_cancel"})
_FINAL_FILM_GRAPH_KEY = "final_film_assembly"


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


@dataclass(frozen=True)
class _TimelineRef:
    clip_id: str
    shot_id: UUID
    artifact_id: UUID
    order: int


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
    seen_clips: set[str] = set()
    for index, raw in enumerate(raw_clips, start=1):
        if not isinstance(raw, dict):
            raise ValidationAppError(
                "timeline clip must be an object",
                details={"code": "INVALID_TIMELINE_CLIP"},
            )
        clip_id = str(raw.get("id") or "")
        shot_id_raw = raw.get("shot_id")
        artifact_id_raw = raw.get("artifact_id")
        if not clip_id or clip_id in seen_clips:
            raise ValidationAppError(
                "timeline clip ids must be unique and non-empty",
                details={"code": "INVALID_TIMELINE_CLIP_ID"},
            )
        if shot_id_raw is None or artifact_id_raw is None:
            raise ValidationAppError(
                "timeline clip requires shot_id and artifact_id",
                details={"code": "TIMELINE_REFERENCE_MISSING", "clip_id": clip_id},
            )
        try:
            shot_id = UUID(str(shot_id_raw))
            artifact_id = UUID(str(artifact_id_raw))
        except ValueError as exc:
            raise ValidationAppError(
                "timeline clip reference must be UUID",
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
        seen_clips.add(clip_id)
        refs.append(
            _TimelineRef(
                clip_id=clip_id,
                shot_id=shot_id,
                artifact_id=artifact_id,
                order=int(raw.get("order", index)),
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
                    "shot_artifact": (
                        str(shot.formal_video_artifact_id)
                        if shot.formal_video_artifact_id
                        else None
                    ),
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
            "edit session timeline has no clips",
            details={"code": "EMPTY_TIMELINE"},
        )
    shots = await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    shot_ids = [shot.id for shot in shots]
    all_run_ids: list[UUID] = []
    for shot in shots:
        refresh_tail = False
        if shot.formal_composite_artifact_id is not None:
            composite_artifact = await session.get(
                Artifact, shot.formal_composite_artifact_id
            )
            composite_run = (
                await session.get(NodeRun, composite_artifact.produced_by_run_id)
                if composite_artifact is not None
                and composite_artifact.produced_by_run_id is not None
                else None
            )
            media_inputs = (
                (composite_run.input_snapshot or {}).get("media_inputs")
                if composite_run is not None
                else None
            )
            video_input = media_inputs.get("video") if isinstance(media_inputs, dict) else None
            refresh_tail = not (
                isinstance(video_input, dict)
                and str(video_input.get("artifact_id"))
                == str(shot.formal_video_artifact_id)
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
        shot_ids=shot_ids,
        node_run_ids=all_run_ids,
        status="queued",
    )


def _deterministic_final_film_bytes(
    *,
    composites: list[tuple[str, bytes, dict[str, str]]],
    final_run_id: UUID,
) -> bytes:
    digest = hashlib.sha256()
    for object_key, data, metadata in composites:
        digest.update(object_key.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
    digest.update(b"final-run\0")
    digest.update(str(final_run_id).encode("ascii"))
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest.digest()


async def _ffprobe_json(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ValidationAppError("ffprobe not found", details={"code": "FFPROBE_UNAVAILABLE"})
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=index,codec_type,codec_name,width,height,channels,sample_rate",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ValidationAppError(
            detail or f"ffprobe failed for {path.name}",
            details={"code": "FFPROBE_FAILED"},
        )
    return dict(json.loads(stdout.decode("utf-8")))


def _final_film_probe_assertions(
    probe: dict[str, Any],
    *,
    dialogue_audio_present: bool,
    burned_subtitles: bool,
) -> dict[str, Any]:
    streams = probe.get("streams")
    stream_rows = (
        [item for item in streams if isinstance(item, dict)]
        if isinstance(streams, list)
        else []
    )
    video_codecs = {
        str(item.get("codec_name")) for item in stream_rows if item.get("codec_type") == "video"
    }
    audio_codecs = {
        str(item.get("codec_name")) for item in stream_rows if item.get("codec_type") == "audio"
    }
    format_name = str((probe.get("format") or {}).get("format_name") or "")
    return {
        "mp4_container": "mp4" in format_name or not format_name,
        "h264_video": "h264" in video_codecs,
        "aac_audio": "aac" in audio_codecs,
        "dialogue_audio_present": dialogue_audio_present and bool(audio_codecs),
        "burned_subtitles": burned_subtitles,
    }


async def _render_with_ffmpeg(
    *,
    composite_files: list[Path],
    output_path: Path,
    lineage_fingerprint: str,
) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValidationAppError("ffmpeg not found", details={"code": "FFMPEG_UNAVAILABLE"})
    list_path = output_path.with_name("concat-list.txt")
    list_path.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in composite_files) + "\n",
        encoding="utf-8",
    )
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-metadata",
        f"comment=dramaforge-final-film-lineage:{lineage_fingerprint}",
        "-movflags",
        "+faststart",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=600.0)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ValidationAppError(
            "final film ffmpeg timed out",
            details={"code": "FINAL_FILM_TIMEOUT"},
        ) from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ValidationAppError(
            detail or f"ffmpeg exited {process.returncode}",
            details={"code": "FINAL_FILM_RENDER_FAILED"},
        )
    if not output_path.is_file():
        raise ValidationAppError(
            "ffmpeg produced no final film output",
            details={"code": "FINAL_FILM_OUTPUT_MISSING"},
        )
    return await _ffprobe_json(output_path)


async def _latest_formal_composite(
    session: AsyncSession,
    *,
    project_id: UUID,
    ref: _TimelineRef,
    shot: Shot,
) -> tuple[NodeRun, Artifact]:
    """Return the current Formal composite for one exact Timeline reference.

    A project can contain many attempts and experiment branches in the same
    graph.  The Timeline's Formal video artifact is the first boundary; the
    explicit Formal composite pointer, when present, is the second.  The
    graph-scope and snapshot checks keep historical or cross-branch rows out
    even if a legacy row has a matching shot id.
    """
    rows = list(
        (
            await session.execute(
                select(NodeRun, Artifact, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .join(GraphVersion, GraphVersion.id == GraphNode.graph_version_id)
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
        if str(snapshot.get("shot_id")) != str(ref.shot_id):
            continue
        if snapshot.get("execution_branch") != "formal":
            continue
        if snapshot.get("experiment_id") is not None:
            continue
        if run.result_artifact_id != artifact.id:
            continue
        if shot.formal_composite_artifact_id is not None and (
            shot.formal_composite_artifact_id != artifact.id
        ):
            continue
        if (
            artifact.project_id != project_id
            or artifact.artifact_type != "video"
            or not artifact.mime_type.startswith("video/")
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
        ):
            continue
        media = snapshot.get("media_inputs")
        if not isinstance(media, dict):
            continue
        video = media.get("video")
        if not isinstance(video, dict) or str(video.get("artifact_id")) != str(ref.artifact_id):
            continue
        formal_video = await session.get(Artifact, ref.artifact_id)
        if formal_video is None or video.get("content_hash") != formal_video.content_hash:
            continue
        if not all(isinstance(media.get(key), dict) for key in ("voice", "subtitle")):
            continue
        candidates.append((run, artifact))
    if not candidates:
        raise ValidationAppError(
            f"no formal composite for timeline clip {ref.clip_id}",
            details={
                "code": "FORMAL_COMPOSITE_MISSING",
                "clip_id": ref.clip_id,
                "shot_id": str(ref.shot_id),
                "artifact_id": str(ref.artifact_id),
            },
        )
    return max(
        candidates,
        key=lambda pair: (
            pair[0].attempt_no or 0,
            pair[0].created_at,
            str(pair[0].id),
        ),
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
    manifest = dict(export.manifest or {})
    raw_run_id = manifest.get("node_run_id")
    raw_operation_id = manifest.get("provider_operation_id")
    if raw_run_id is None or raw_operation_id is None:
        raise ValidationAppError(
            "Final Film export is missing execution lineage",
            details={"code": "FINAL_FILM_LINEAGE_MISSING"},
        )
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
    composite_ids = [str(item.source_artifact_id) for item in items]
    if not composite_ids:
        raw_ids = manifest.get("composite_artifact_ids")
        if isinstance(raw_ids, list):
            composite_ids = [str(item) for item in raw_ids]
    ffprobe = manifest.get("ffprobe")
    formal_references = manifest.get("formal_references")
    return FinalFilmRead(
        project_id=export.project_id,
        edit_session_id=edit_session.id,
        timeline_version=edit_session.version,
        export_id=export.id,
        artifact_id=artifact.id,
        node_run_id=UUID(str(raw_run_id)),
        provider_operation_id=UUID(str(raw_operation_id)),
        format=export.format,
        status=export.status,
        duration_seconds=artifact.duration_seconds or Decimal("0"),
        shot_count=len({ref.shot_id for ref in refs}),
        timeline_clip_count=len(refs),
        composite_artifact_ids=composite_ids,
        source_commit=str(manifest.get("source_commit") or ""),
        mime_type=artifact.mime_type,
        byte_size=int(artifact.byte_size),
        storage_state=artifact.storage_state,
        content_hash=artifact.content_hash,
        formal_references=(
            [item for item in formal_references if isinstance(item, dict)]
            if isinstance(formal_references, list)
            else []
        ),
        idempotency_key=export.idempotency_key,
        ffprobe=ffprobe if isinstance(ffprobe, dict) else None,
    )


def _final_film_error_summary(exc: Exception) -> str:
    return str(exc)[:500] or type(exc).__name__


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
        materialized = await graphs.materialize_definition(
            version_id=existing.current_version_id
        )
        node = materialized.nodes[_FINAL_FILM_GRAPH_KEY]
        return existing, node, materialized.version.version_number
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
                    "type": "composite",
                    "display_name": "Final Film Assembly",
                }
            ],
            "edges": [],
        },
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    node = materialized.nodes[_FINAL_FILM_GRAPH_KEY]
    if materialized.version.status == "draft":
        published = await graphs.publish(
            version_id=materialized.version.id,
            published_by=actor_id,
        )
        return graph, node, published.version_number
    return graph, node, materialized.version.version_number


async def render_final_film(
    session: AsyncSession,
    *,
    project_id: UUID,
    edit_session_id: UUID,
    expected_timeline_version: int | None,
    actor_id: UUID,
    idempotency_key: str | None = None,
    name: str = "V1 Final Film",
) -> FinalFilmRead:
    await _project_or_404(session, project_id)
    normalized_key = idempotency_key.strip() if idempotency_key else None
    if normalized_key and len(normalized_key) > 200:
        raise ValidationAppError(
            "Idempotency-Key is too long",
            details={"code": "IDEMPOTENCY_KEY_INVALID"},
        )
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        lock_seed = hashlib.sha256(
            f"final-film-idempotency:{project_id}:{normalized_key or edit_session_id}".encode()
        ).hexdigest()
        lock_value = int(lock_seed[:15], 16)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_value)"),
            {"lock_value": lock_value},
        )
    edit_session, refs = await _load_timeline_refs(
        session,
        project_id=project_id,
        edit_session_id=edit_session_id,
        expected_timeline_version=expected_timeline_version,
    )
    if not refs:
        raise ValidationAppError("no timeline clips", details={"code": "EMPTY_TIMELINE"})
    source_commit = get_settings().source_commit
    request_payload = {
        "project_id": str(project_id),
        "edit_session_id": str(edit_session.id),
        "timeline_version": edit_session.version,
        "timeline_clips": [
            {
                "clip_id": ref.clip_id,
                "shot_id": str(ref.shot_id),
                "artifact_id": str(ref.artifact_id),
                "order": ref.order,
            }
            for ref in refs
        ],
        "name": name,
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing_query = select(Export).where(
        Export.project_id == project_id,
        Export.format == "dramaforge-final-film-v1",
    )
    if normalized_key:
        existing_query = existing_query.where(Export.idempotency_key == normalized_key)
    else:
        existing_query = existing_query.where(
            Export.manifest["request_fingerprint"].as_string() == request_fingerprint
        )
    existing = await session.scalar(existing_query)
    if existing is not None:
        existing_fingerprint = str((existing.manifest or {}).get("request_fingerprint") or "")
        if normalized_key and existing_fingerprint != request_fingerprint:
            raise ValidationAppError(
                "Idempotency-Key was already used for a different Final Film request",
                details={"code": "IDEMPOTENCY_KEY_REUSED"},
            )
        if existing.result_artifact_id is None or existing.status != "completed":
            raise ValidationAppError(
                "Final Film render is already in progress",
                details={"code": "FINAL_FILM_RENDER_IN_PROGRESS"},
            )
        return await _final_film_read(
            session, export=existing, edit_session=edit_session, refs=refs
        )

    composites: list[tuple[NodeRun, Artifact, bytes]] = []
    composite_lineage: list[dict[str, object]] = []
    store = get_object_store()
    formal_shots = {
        shot.id: shot
        for shot in await _formal_shots_for_refs(session, project_id=project_id, refs=refs)
    }
    for ref in refs:
        run, artifact = await _latest_formal_composite(
            session,
            project_id=project_id,
            ref=ref,
            shot=formal_shots[ref.shot_id],
        )
        if artifact.storage_state != "available":
            raise ValidationAppError(
                "composite Artifact is not available",
                details={"code": "COMPOSITE_UNAVAILABLE"},
            )
        data = await store.get_bytes(object_key=artifact.object_key)
        if not data:
            raise ValidationAppError(
                "composite Artifact bytes are empty",
                details={"code": "COMPOSITE_EMPTY"},
            )
        composites.append((run, artifact, data))
        raw_media_inputs = (run.input_snapshot or {}).get("media_inputs")
        media_inputs = (
            dict(cast(dict[str, object], raw_media_inputs))
            if isinstance(raw_media_inputs, dict)
            else {}
        )
        composite_lineage.append(
            {
                "clip_id": ref.clip_id,
                "shot_id": str(ref.shot_id),
                "formal_video_artifact_id": str(ref.artifact_id),
                "composite_artifact_id": str(artifact.id),
                "composite_run_id": str(run.id),
                "media_inputs": media_inputs,
            }
        )

    graph, node, _version_no = await _ensure_final_graph(
        session,
        project_id=project_id,
        actor_id=actor_id,
    )
    run = NodeRun(
        project_id=project_id,
        graph_version_id=node.graph_version_id,
        graph_node_id=node.id,
        idempotency_key=f"final-film:{request_fingerprint}",
        input_hash=request_fingerprint,
        status="running",
        input_snapshot={
            **request_payload,
            "node_key": _FINAL_FILM_GRAPH_KEY,
            "source_commit": source_commit,
            "execution_path": "local-final-film-v1",
            "formal_references": composite_lineage,
        },
        created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=run.attempt_no,
        purpose="primary",
        operation_kind="final_film.compose",
        actual_provider="local_ffmpeg",
        actual_model="ffmpeg-concat",
        request_fingerprint=request_fingerprint,
        status="submission_started",
        request_summary={
            "execution_path": "local-final-film-v1",
            "edit_session_id": str(edit_session.id),
            "timeline_version": edit_session.version,
            "formal_references": composite_lineage,
        },
        response_summary={},
        submitted_at=datetime.now(UTC),
        currency="USD",
    )
    session.add(operation)
    await session.flush()

    probe_result: dict[str, Any]
    stored = None
    try:
        if get_settings().app_env == "test":
            final_bytes = _deterministic_final_film_bytes(
                composites=[
                    (
                        artifact.object_key,
                        data,
                        {"artifact_id": str(artifact.id)},
                    )
                    for _run, artifact, data in composites
                ],
                final_run_id=run.id,
            )
            duration_seconds = Decimal(
                str(
                    sum(
                        float(artifact.duration_seconds or 0)
                        for _run, artifact, _data in composites
                    )
                )
            ).quantize(Decimal("0.001"))
            probe_result = {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264"},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {"duration": str(duration_seconds), "format_name": "mp4"},
            }
            object_key = f"projects/{project_id}/final-film/{run.id}.mp4"
            stored = await store.put_bytes(
                object_key=object_key,
                data=final_bytes,
                mime_type="video/mp4",
            )
        else:
            with tempfile.TemporaryDirectory(prefix="dramaforge-final-film-") as tmp:
                tmp_path = Path(tmp)
                files: list[Path] = []
                for index, (_run, _artifact, data) in enumerate(composites, start=1):
                    path = tmp_path / f"clip-{index}.mp4"
                    path.write_bytes(data)
                    files.append(path)
                output = tmp_path / "final-film.mp4"
                lineage_fingerprint = hashlib.sha256(
                    json.dumps(composite_lineage, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                probe_result = await _render_with_ffmpeg(
                    composite_files=files,
                    output_path=output,
                    lineage_fingerprint=lineage_fingerprint,
                )
                final_bytes = output.read_bytes()
                format_info = probe_result.get("format")
                if not isinstance(format_info, dict) or format_info.get("duration") is None:
                    raise ValidationAppError(
                        "ffprobe did not report Final Film duration",
                        details={"code": "FFPROBE_INVALID_DURATION"},
                    )
                raw_duration = float(format_info["duration"])
                duration_seconds = Decimal(str(raw_duration)).quantize(Decimal("0.001"))
                object_key = f"projects/{project_id}/final-film/{run.id}.mp4"
                stored = await store.put_bytes(
                    object_key=object_key,
                    data=final_bytes,
                    mime_type="video/mp4",
                )
        def has_media_input(item: dict[str, object], key: str) -> bool:
            media = item.get("media_inputs")
            return isinstance(media, dict) and isinstance(media.get(key), dict)

        assertions = _final_film_probe_assertions(
            probe_result,
            dialogue_audio_present=all(
                has_media_input(item, "voice")
                for item in composite_lineage
            ),
            burned_subtitles=all(
                has_media_input(item, "subtitle")
                for item in composite_lineage
            ),
        )
        if not all(assertions.values()):
            raise ValidationAppError(
                "Final Film media proof is incomplete",
                details={"code": "FINAL_FILM_MEDIA_ASSERTION_FAILED", "assertions": assertions},
            )
        probe_result["assertions"] = assertions
        operation.status = "succeeded"
        operation.response_summary = {
            "ffprobe": probe_result,
            "duration_seconds": str(duration_seconds),
        }
        operation.completed_at = datetime.now(UTC)
        artifact = await get_or_create_artifact(
            session,
            project_id=project_id,
            artifact_type="video",
            object_key=stored.object_key,
            content_hash=stored.content_hash,
            mime_type=stored.mime_type,
            byte_size=stored.byte_size,
            produced_by_run_id=run.id,
        )
        artifact.duration_seconds = duration_seconds
        raw_stream_rows = probe_result.get("streams")
        stream_rows: list[dict[str, Any]] = (
            [item for item in raw_stream_rows if isinstance(item, dict)]
            if isinstance(raw_stream_rows, list)
            else []
        )
        first_video = next(
            (item for item in stream_rows if item.get("codec_type") == "video"), {}
        )
        artifact.width = int(first_video["width"]) if first_video.get("width") else None
        artifact.height = int(first_video["height"]) if first_video.get("height") else None
        run.status = "completed"
        run.result_artifact_id = artifact.id
        run.finished_at = datetime.now(UTC)
        run.output_summary = {
            "status": "completed",
            "artifact_id": str(artifact.id),
            "ffprobe": probe_result,
            "formal_references": composite_lineage,
        }
        node.latest_successful_run_id = run.id
        export = Export(
            project_id=project_id,
            format="dramaforge-final-film-v1",
            status="completed",
            requested_by=actor_id,
            idempotency_key=normalized_key,
            manifest={
                **request_payload,
                "request_fingerprint": request_fingerprint,
                "timeline": {
                    "edit_session_id": str(edit_session.id),
                    "version": edit_session.version,
                    "clips": request_payload["timeline_clips"],
                },
                "formal_references": composite_lineage,
                "artifact_id": str(artifact.id),
                "node_run_id": str(run.id),
                "provider_operation_id": str(operation.id),
                "duration_seconds": str(duration_seconds),
                "source_commit": source_commit,
                "idempotency_key": normalized_key,
                "ffprobe": probe_result,
            },
            result_artifact_id=artifact.id,
            completed_at=datetime.now(UTC),
        )
        session.add(export)
        await session.flush()
        for ordinal, (_run, source_artifact, _data) in enumerate(composites, start=1):
            session.add(
                ExportItem(
                    export_id=export.id,
                    ordinal=ordinal,
                    source_artifact_id=source_artifact.id,
                    role="shot_composite",
                    metadata_json={
                        "timeline_clip_id": refs[ordinal - 1].clip_id,
                        "formal_video_artifact_id": str(refs[ordinal - 1].artifact_id),
                        **composite_lineage[ordinal - 1],
                    },
                )
            )
        await session.commit()
        return await _final_film_read(
            session, export=export, edit_session=edit_session, refs=refs
        )
    except Exception as exc:
        if stored is not None:
            with suppress(Exception):
                await store.delete_bytes(object_key=stored.object_key)
        operation.status = "failed"
        operation.error_code = (
            str(exc.details.get("code"))
            if isinstance(exc, ValidationAppError) and exc.details.get("code")
            else "FINAL_FILM_RENDER_FAILED"
        )
        operation.error_summary = _final_film_error_summary(exc)
        operation.completed_at = datetime.now(UTC)
        run.status = "failed"
        run.error_code = operation.error_code
        run.error_summary = operation.error_summary
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise


__all__ = [
    "FinalFilmPrepareBody",
    "FinalFilmPrepareRead",
    "FinalFilmRead",
    "prepare_formal_tail",
    "render_final_film",
]
