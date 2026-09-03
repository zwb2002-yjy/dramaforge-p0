"""Formal Shot tail and Final Film assembly (V1 Final Film Artifact).

The Workbench API dispatches paid keyframe/video nodes.  After their results
are marked Formal, this service queues the zero-Provider local tail nodes
(voice / subtitle / video-drift review / composite / continuity review) for
the same shot graph, then concatenates each shot composite into one playable
Final Film Artifact and records Export/ExportItem lineage.

No Provider fallback and no paid submit is performed here; voice is the local
TTS runtime, subtitle and reviews are pure local nodes, and composite/Final
Film are rendered by the local FFmpeg runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Episode, Scene, Shot
from app.config import get_settings
from app.delivery.models import Export, ExportItem
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.experiment_nodes import queue_branch_nodes
from app.execution.models import Artifact, GraphNode, NodeRun
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


class FinalFilmPrepareRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    shot_ids: list[UUID]
    node_run_ids: list[UUID]
    status: str = "queued"


class FinalFilmRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    export_id: UUID
    artifact_id: UUID
    format: str
    status: str
    duration_seconds: Decimal
    shot_count: int
    composite_artifact_ids: list[str]
    source_commit: str


async def _project_or_404(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("project not found")
    return project


async def prepare_formal_tail(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor: User,
    shot_ids: list[UUID] | None = None,
) -> FinalFilmPrepareRead:
    """Queue voice/subtitle/review/composite tail runs for Formal shots."""
    await _project_or_404(session, project_id)
    if shot_ids is None:
        shots = list(
            (
                await session.execute(
                    select(Shot)
                    .where(Shot.project_id == project_id)
                    .order_by(Shot.sort_order, Shot.shot_number)
                )
            )
            .scalars()
            .all()
        )
        shot_ids = [shot.id for shot in shots]
    if not shot_ids:
        raise ValidationAppError(
            "project has no shots to prepare", details={"code": "NO_SHOTS"}
        )

    all_run_ids: list[UUID] = []
    for shot_id in shot_ids:
        shot = await session.get(Shot, shot_id)
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError(
                "shot does not belong to project",
                details={"code": "SHOT_SCOPE_MISMATCH"},
            )
        if shot.formal_video_artifact_id is None:
            raise ValidationAppError(
                "formal tail requires a formal video",
                details={
                    "code": "FORMAL_VIDEO_REQUIRED",
                    "shot_id": str(shot.id),
                },
            )
        run_ids = await queue_branch_nodes(
            session,
            project_id=project_id,
            shot_id=shot_id,
            user_id=actor.id,
            node_keys=list(_TAIL_NODE_KEYS),
            include_missing_dependencies=True,
        )
        all_run_ids.extend(run_ids)
    await session.commit()
    return FinalFilmPrepareRead(
        project_id=project_id,
        shot_ids=shot_ids,
        node_run_ids=all_run_ids,
        status="queued",
    )


def _deterministic_final_film_bytes(
    *,
    composites: list[tuple[str, bytes, dict[str, str]]],
) -> bytes:
    digest = hashlib.sha256()
    for object_key, data, metadata in composites:
        digest.update(object_key.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest.digest()


async def _ffprobe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ValidationAppError(
            "ffprobe not found", details={"code": "FFPROBE_UNAVAILABLE"}
        )
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:300]
        raise ValidationAppError(
            detail or f"ffprobe failed for {path.name}",
            details={"code": "FFPROBE_FAILED"},
        )
    try:
        return float(stdout.decode("ascii").strip())
    except ValueError as exc:
        raise ValidationAppError(
            f"invalid duration for {path.name}",
            details={"code": "FFPROBE_INVALID_DURATION"},
        ) from exc


async def _render_with_ffmpeg(
    *,
    composite_files: list[Path],
    output_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValidationAppError(
            "ffmpeg not found", details={"code": "FFMPEG_UNAVAILABLE"}
        )
    list_path = output_path.with_name("concat-list.txt")
    list_path.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in composite_files)
        + "\n",
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


async def _latest_composite(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot: Shot,
) -> tuple[NodeRun, Artifact]:
    rows = list(
        (
            await session.execute(
                select(NodeRun, Artifact, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .join(Artifact, Artifact.id == NodeRun.result_artifact_id)
                .where(NodeRun.project_id == project_id)
                .where(NodeRun.status.in_(_DONE))
                .where(GraphNode.node_key == "composite")
                .order_by(NodeRun.attempt_no.desc(), NodeRun.created_at.desc())
            )
        )
        .tuples()
        .all()
    )
    candidates = [
        (run, artifact, node)
        for run, artifact, node in rows
        if str((run.input_snapshot or {}).get("shot_id")) == str(shot.id)
    ]
    if not candidates:
        raise ValidationAppError(
            f"shot {shot.shot_number} has no completed composite",
            details={"code": "COMPOSITE_NOT_COMPLETE", "shot_id": str(shot.id)},
        )
    run, artifact, _node = candidates[0]
    return run, artifact


async def render_final_film(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor: User,
    name: str = "V1 Final Film",
) -> FinalFilmRead:
    """Concatenate completed shot composites into one playable MP4 Artifact."""
    await _project_or_404(session, project_id)
    shots = list(
        (
            await session.execute(
                select(Shot)
                .join(Scene, Scene.id == Shot.scene_id)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Episode.project_id == project_id)
                .order_by(Episode.episode_number, Scene.scene_number, Shot.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not shots:
        raise ValidationAppError(
            "no shots found for final film", details={"code": "NO_SHOTS"}
        )

    store = get_object_store()
    composites: list[tuple[NodeRun, Artifact, bytes]] = []
    for shot in shots:
        run, artifact = await _latest_composite(
            session, project_id=project_id, shot=shot
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

    if get_settings().app_env == "test":
        final_bytes = _deterministic_final_film_bytes(
            composites=[
                (artifact.object_key, data, {"artifact_id": str(artifact.id)})
                for _run, artifact, data in composites
            ]
        )
        duration_seconds = Decimal(
            str(
                sum(
                    float(artifact.duration_seconds or 0)
                    for _run, artifact, _data in composites
                )
            )
        ).quantize(Decimal("0.001"))
        object_key = f"projects/{project_id}/final-film/{uuid4()}.mp4"
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
                path = tmp_path / f"shot-{index}.mp4"
                path.write_bytes(data)
                files.append(path)
            output = tmp_path / "final-film.mp4"
            await _render_with_ffmpeg(composite_files=files, output_path=output)
            final_bytes = output.read_bytes()
            raw_duration = await _ffprobe_duration(output)
            duration_seconds = Decimal(str(raw_duration)).quantize(Decimal("0.001"))
            object_key = f"projects/{project_id}/final-film/{_stamp()}.mp4"
            stored = await store.put_bytes(
                object_key=object_key,
                data=final_bytes,
                mime_type="video/mp4",
            )

    artifact = await get_or_create_artifact(
        session,
        project_id=project_id,
        artifact_type="video",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=None,
    )
    artifact.duration_seconds = duration_seconds
    await session.flush()
    export = Export(
        project_id=project_id,
        format="dramaforge-final-film-v1",
        status="completed",
        requested_by=actor.id,
        manifest={
            "artifact_id": str(artifact.id),
            "duration_seconds": str(duration_seconds),
            "shot_count": len(composites),
            "source_commit": get_settings().source_commit,
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
                    "composite_artifact_id": str(source_artifact.id),
                    "composite_run_id": str(_run.id),
                },
            )
        )
    await session.commit()
    return FinalFilmRead(
        project_id=project_id,
        export_id=export.id,
        artifact_id=artifact.id,
        format=export.format,
        status=export.status,
        duration_seconds=duration_seconds,
        shot_count=len(composites),
        composite_artifact_ids=[str(source.id) for _run, source, _data in composites],
        source_commit=get_settings().source_commit,
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


__all__ = [
    "FinalFilmPrepareRead",
    "FinalFilmRead",
    "prepare_formal_tail",
    "render_final_film",
]
