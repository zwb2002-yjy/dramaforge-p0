"""S5 product export: timeline JSON, SRT, package manifest, optional FFmpeg MP4."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, NodeRun
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


@dataclass(frozen=True)
class ExportResult:
    export_id: UUID
    project_id: UUID
    timeline_json: str
    srt: str
    package_manifest: str
    timeline_hash: str
    srt_hash: str
    package_hash: str
    mp4_object_key: str | None
    mp4_hash: str | None
    mp4_error: str | None
    source_artifact_ids: list[UUID]
    source_node_run_ids: list[UUID]


async def build_project_export(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_subtitles: list[tuple[str, str]],
    store: ObjectStore | None = None,
    try_ffmpeg: bool = True,
) -> ExportResult:
    """Build deliverables from available Artifacts; FFmpeg when binary present."""
    arts = list(
        (
            await session.execute(
                select(Artifact)
                .where(Artifact.project_id == project_id)
                .where(Artifact.storage_state == "available")
            )
        )
        .scalars()
        .all()
    )
    if not arts:
        raise ValidationAppError("no available artifacts to export")
    runs = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .where(NodeRun.status.in_(("completed", "cached", "completed_after_cancel")))
            )
        )
        .scalars()
        .all()
    )
    timeline = {
        "version": "timeline-p0-v1",
        "project_id": str(project_id),
        "shots": [
            {"id": sid, "subtitle": sub, "artifact_count": len(arts)}
            for sid, sub in shot_subtitles
        ],
        "artifact_hashes": [a.content_hash for a in arts],
        "node_run_ids": [str(r.id) for r in runs],
    }
    timeline_json = json.dumps(timeline, sort_keys=True, separators=(",", ":"))
    srt_lines: list[str] = []
    for i, (_sid, text) in enumerate(shot_subtitles or [("1", "Shot")], start=1):
        srt_lines.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n{text}\n")
    srt = "\n".join(srt_lines)
    package = {
        "version": "asset-package-p0-v1",
        "project_id": str(project_id),
        "items": [
            {
                "artifact_id": str(a.id),
                "object_key": a.object_key,
                "content_hash": a.content_hash,
                "mime_type": a.mime_type,
                "byte_size": a.byte_size,
            }
            for a in arts
        ],
    }
    package_manifest = json.dumps(package, sort_keys=True, separators=(",", ":"))
    export_id = uuid4()
    obj = store or get_object_store()
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export_id}/timeline.json",
        data=timeline_json.encode(),
        mime_type="application/json",
    )
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export_id}/subtitles.srt",
        data=srt.encode(),
        mime_type="application/x-subrip",
    )
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export_id}/package.json",
        data=package_manifest.encode(),
        mime_type="application/json",
    )

    mp4_key: str | None = None
    mp4_hash: str | None = None
    mp4_error: str | None = None
    if try_ffmpeg:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            mp4_error = "FFMPEG_NOT_FOUND"
        else:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "program.mp4"
                    # Minimal valid-ish generation: color source 1s
                    subprocess.run(
                        [
                            ffmpeg,
                            "-y",
                            "-f",
                            "lavfi",
                            "-i",
                            "color=c=black:s=720x1280:d=1",
                            "-c:v",
                            "libx264",
                            "-t",
                            "1",
                            str(out),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    data = out.read_bytes()
                    mp4_key = f"exports/{project_id}/{export_id}/program.mp4"
                    stored = await obj.put_bytes(
                        object_key=mp4_key, data=data, mime_type="video/mp4"
                    )
                    mp4_hash = stored.content_hash
            except Exception as exc:  # noqa: BLE001
                mp4_error = f"FFMPEG_FAILED: {exc}"[:300]
    else:
        mp4_error = "FFMPEG_SKIPPED"

    return ExportResult(
        export_id=export_id,
        project_id=project_id,
        timeline_json=timeline_json,
        srt=srt,
        package_manifest=package_manifest,
        timeline_hash=hashlib.sha256(timeline_json.encode()).hexdigest(),
        srt_hash=hashlib.sha256(srt.encode()).hexdigest(),
        package_hash=hashlib.sha256(package_manifest.encode()).hexdigest(),
        mp4_object_key=mp4_key,
        mp4_hash=mp4_hash,
        mp4_error=mp4_error,
        source_artifact_ids=[a.id for a in arts],
        source_node_run_ids=[r.id for r in runs],
    )
