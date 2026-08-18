"""Local media input resolution and rendering for composite nodes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.execution.models import Artifact, GraphNode, NodeRun
from app.storage.minio_store import ObjectStore

_SUCCESS_STATUSES = frozenset({"completed", "cached", "completed_after_cancel"})
_PENDING_STATUSES = frozenset({"queued", "running"})
_MEDIA_REQUIREMENTS = {
    "video": ("video", "video/"),
    "voice": ("audio", "audio/"),
    "subtitle": ("subtitle", "application/x-subrip"),
}


class CompositeInputMissingError(RuntimeError):
    """Raised when a required composite input cannot be consumed."""


class CompositeRenderError(RuntimeError):
    """Raised when local FFmpeg rendering fails."""


@dataclass(frozen=True)
class CompositeInputs:
    """Resolved media bytes and immutable lineage for one composite execution."""

    composite_run_id: str
    media_inputs: dict[str, dict[str, str]]
    video: bytes
    voice: bytes
    subtitle: bytes


def composite_lineage_fingerprint(inputs: CompositeInputs) -> str:
    """Return a stable identity for one composite output and its source lineage.

    FFmpeg can emit byte-identical containers when a composite is re-run with
    unchanged source media. The final output must remain independently
    attributable to its NodeRun, so bind the output run ID and source lineage
    into the container metadata and test fixture bytes.
    """
    raw = json.dumps(
        {
            "composite_run_id": inputs.composite_run_id,
            "media_inputs": inputs.media_inputs,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


async def composite_inputs_pending(
    session: AsyncSession,
    *,
    run: NodeRun,
) -> bool:
    """Return whether this composite is waiting for a newer source attempt.

    The shot start endpoint queues the whole pipeline together. A composite
    must remain unclaimed while the latest video, voice, or subtitle attempt
    for its shot is queued or running. Absent, failed, or unreadable media is
    intentionally left for the terminal fail-closed resolution path.
    """
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None or node.node_key != "composite":
        return False

    shot_id = str((run.input_snapshot or {}).get("shot_id") or "").strip()
    if not shot_id:
        return False

    rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(NodeRun.project_id == run.project_id)
                .where(NodeRun.graph_version_id == run.graph_version_id)
                .where(GraphNode.graph_version_id == run.graph_version_id)
                .where(GraphNode.node_key.in_(tuple(_MEDIA_REQUIREMENTS)))
            )
        )
        .tuples()
        .all()
    )

    latest_by_key: dict[str, NodeRun] = {}
    for source_run, source_node in rows:
        if str((source_run.input_snapshot or {}).get("shot_id") or "") != shot_id:
            continue
        key = source_node.node_key
        current = latest_by_key.get(key)
        if current is None or (
            source_run.attempt_no,
            source_run.created_at,
            str(source_run.id),
        ) > (
            current.attempt_no,
            current.created_at,
            str(current.id),
        ):
            latest_by_key[key] = source_run

    return any(source.status in _PENDING_STATUSES for source in latest_by_key.values())


async def resolve_composite_inputs(
    session: AsyncSession,
    *,
    run: NodeRun,
    store: ObjectStore,
) -> CompositeInputs:
    """Resolve the latest successful video, voice, and subtitle for this shot."""
    shot_id = str((run.input_snapshot or {}).get("shot_id") or "").strip()
    if not shot_id:
        raise CompositeInputMissingError("composite run has no shot_id")

    rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode, Artifact)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .outerjoin(Artifact, Artifact.id == NodeRun.result_artifact_id)
                .where(NodeRun.project_id == run.project_id)
                .where(NodeRun.graph_version_id == run.graph_version_id)
                .where(NodeRun.status.in_(_SUCCESS_STATUSES))
                .where(GraphNode.graph_version_id == run.graph_version_id)
                .where(GraphNode.node_key.in_(tuple(_MEDIA_REQUIREMENTS)))
            )
        )
        .tuples()
        .all()
    )

    selected: dict[str, tuple[NodeRun, Artifact | None]] = {}
    for source_run, source_node, artifact in rows:
        key = source_node.node_key
        if str((source_run.input_snapshot or {}).get("shot_id") or "") != shot_id:
            continue
        current = selected.get(key)
        if current is None or (
            source_run.attempt_no,
            source_run.created_at,
            str(source_run.id),
        ) > (
            current[0].attempt_no,
            current[0].created_at,
            str(current[0].id),
        ):
            selected[key] = (source_run, artifact)

    bytes_by_key: dict[str, bytes] = {}
    media_inputs: dict[str, dict[str, str]] = {}
    for key, (expected_type, expected_mime) in _MEDIA_REQUIREMENTS.items():
        source = selected.get(key)
        if source is None:
            raise CompositeInputMissingError(f"{key} has no successful source run")
        source_run, source_artifact = source
        if source_artifact is None:
            raise CompositeInputMissingError(f"{key} source run has no Artifact")
        if source_artifact.storage_state != "available" or source_artifact.deleted_at is not None:
            raise CompositeInputMissingError(f"{key} Artifact is not available")
        if (
            source_artifact.artifact_type != expected_type
            or not source_artifact.mime_type.startswith(expected_mime)
        ):
            raise CompositeInputMissingError(f"{key} Artifact has invalid type or MIME type")
        try:
            data = await store.get_bytes(object_key=source_artifact.object_key)
        except Exception as exc:  # noqa: BLE001 - ObjectStore implementations vary
            raise CompositeInputMissingError(f"{key} Artifact cannot be read") from exc
        if not data:
            raise CompositeInputMissingError(f"{key} Artifact is empty")
        if hashlib.sha256(data).hexdigest() != source_artifact.content_hash:
            raise CompositeInputMissingError(f"{key} Artifact content hash does not match")
        bytes_by_key[key] = data
        media_inputs[key] = {
            "artifact_id": str(source_artifact.id),
            "object_key": source_artifact.object_key,
            "content_hash": source_artifact.content_hash,
            "mime_type": source_artifact.mime_type,
            "source_node_run_id": str(source_run.id),
        }

    return CompositeInputs(
        composite_run_id=str(run.id),
        media_inputs=media_inputs,
        video=bytes_by_key["video"],
        voice=bytes_by_key["voice"],
        subtitle=bytes_by_key["subtitle"],
    )


async def render_composite_bytes(inputs: CompositeInputs) -> bytes:
    """Render media locally, using deterministic bytes only in the test environment."""
    if get_settings().app_env == "test":
        return deterministic_composite_test_bytes(inputs)
    return await _render_with_ffmpeg(inputs)


def deterministic_composite_test_bytes(inputs: CompositeInputs) -> bytes:
    """Return stable MP4-signatured bytes without requiring FFmpeg in unit tests."""
    digest = hashlib.sha256()
    for key, data in (
        ("video", inputs.video),
        ("voice", inputs.voice),
        ("subtitle", inputs.subtitle),
    ):
        digest.update(key.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    digest.update(b"lineage\0")
    digest.update(composite_lineage_fingerprint(inputs).encode("ascii"))
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest.digest()


async def _render_with_ffmpeg(inputs: CompositeInputs) -> bytes:
    """Mux voice and burn SRT subtitles into an MP4 with the local FFmpeg executable."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CompositeRenderError("ffmpeg executable not found")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CompositeRenderError("ffprobe executable not found")
    lineage_fingerprint = composite_lineage_fingerprint(inputs)

    with tempfile.TemporaryDirectory(prefix="dramaforge-composite-") as tmp:
        tmp_path = Path(tmp)
        video_path = tmp_path / "video.mp4"
        voice_path = tmp_path / "voice.wav"
        subtitle_path = tmp_path / "subtitle.srt"
        output_path = tmp_path / "composite.mp4"
        video_path.write_bytes(inputs.video)
        voice_path.write_bytes(inputs.voice)
        subtitle_path.write_bytes(inputs.subtitle)

        async def media_duration(path: Path) -> float:
            probe = await asyncio.create_subprocess_exec(
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
            stdout, stderr = await probe.communicate()
            if probe.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()[:300]
                raise CompositeRenderError(detail or f"ffprobe failed for {path.name}")
            try:
                return float(stdout.decode("ascii").strip())
            except ValueError as exc:
                raise CompositeRenderError(f"invalid duration for {path.name}") from exc

        video_duration = await media_duration(video_path)
        voice_duration = await media_duration(voice_path)
        if voice_duration > video_duration + 0.1:
            raise CompositeRenderError(
                "voice duration exceeds video duration "
                f"({voice_duration:.2f}s > {video_duration:.2f}s)"
            )

        subtitle_filter_path = (
            subtitle_path.as_posix().replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        )
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(voice_path),
            "-vf",
            f"subtitles=filename='{subtitle_filter_path}'",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-af",
            "apad",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-metadata",
            f"comment=dramaforge-composite-lineage:{lineage_fingerprint}",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=300.0)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise CompositeRenderError("ffmpeg timed out") from exc

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:300]
            message = detail or f"ffmpeg failed with exit code {process.returncode}"
            raise CompositeRenderError(message)
        if not output_path.is_file():
            raise CompositeRenderError("ffmpeg did not produce output")
        data = output_path.read_bytes()
        if len(data) < 32 or b"ftyp" not in data[:32]:
            raise CompositeRenderError("ffmpeg output is not a valid MP4")
        return data
