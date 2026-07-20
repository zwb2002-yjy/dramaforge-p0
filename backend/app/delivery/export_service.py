"""S5 export: Export/ExportItem + reproducible content hashes + fail-closed MP4."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.models import Export, ExportItem
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
    export_item_count: int
    export_status: str


def content_timeline(
    *,
    project_id: UUID,
    shot_subtitles: list[tuple[str, str]],
    artifact_hashes: list[str],
    node_run_ids: list[str],
) -> dict[str, object]:
    """Stable timeline body (no export_id) for reproducible hashing."""
    return {
        "version": "timeline-p0-v1",
        "project_id": str(project_id),
        "shots": [
            {"id": sid, "subtitle": sub, "artifact_count": len(artifact_hashes)}
            for sid, sub in shot_subtitles
        ],
        "artifact_hashes": sorted(artifact_hashes),
        "node_run_ids": sorted(node_run_ids),
    }


def content_package(
    *,
    project_id: UUID,
    items: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "version": "asset-package-p0-v1",
        "project_id": str(project_id),
        "items": sorted(items, key=lambda x: str(x.get("content_hash", ""))),
    }


async def build_project_export(
    session: AsyncSession,
    *,
    project_id: UUID,
    requested_by: UUID,
    shot_subtitles: list[tuple[str, str]],
    store: ObjectStore | None = None,
    try_ffmpeg: bool = True,
) -> ExportResult:
    arts = list(
        (
            await session.execute(
                select(Artifact)
                .where(Artifact.project_id == project_id)
                .where(Artifact.storage_state == "available")
                .where(Artifact.artifact_type != "export_package")
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

    export = Export(
        project_id=project_id,
        format="timeline_json",
        status="running",
        requested_by=requested_by,
        manifest={},
        started_at=datetime.now(UTC),
    )
    session.add(export)
    await session.flush()

    for i, art in enumerate(arts, start=1):
        session.add(
            ExportItem(
                export_id=export.id,
                ordinal=i,
                source_artifact_id=art.id,
                role=art.artifact_type,
                metadata_json={
                    "content_hash": art.content_hash,
                    "object_key": art.object_key,
                    "byte_size": art.byte_size,
                    "produced_by_run_id": str(art.produced_by_run_id)
                    if art.produced_by_run_id
                    else None,
                },
            )
        )

    subs = shot_subtitles or [("1", "Shot")]
    timeline_body = content_timeline(
        project_id=project_id,
        shot_subtitles=subs,
        artifact_hashes=[a.content_hash for a in arts],
        node_run_ids=[str(r.id) for r in runs],
    )
    timeline_json = json.dumps(timeline_body, sort_keys=True, separators=(",", ":"))
    srt_lines: list[str] = []
    for i, (_sid, text) in enumerate(subs, start=1):
        srt_lines.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n{text}\n")
    srt = "\n".join(srt_lines)
    package_body = content_package(
        project_id=project_id,
        items=[
            {
                "content_hash": a.content_hash,
                "mime_type": a.mime_type,
                "byte_size": a.byte_size,
                "artifact_type": a.artifact_type,
            }
            for a in arts
        ],
    )
    package_manifest = json.dumps(package_body, sort_keys=True, separators=(",", ":"))
    timeline_hash = hashlib.sha256(timeline_json.encode()).hexdigest()
    srt_hash = hashlib.sha256(srt.encode()).hexdigest()
    package_hash = hashlib.sha256(package_manifest.encode()).hexdigest()

    obj = store or get_object_store()
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export.id}/timeline.json",
        data=timeline_json.encode(),
        mime_type="application/json",
    )
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export.id}/subtitles.srt",
        data=srt.encode(),
        mime_type="application/x-subrip",
    )
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export.id}/package.json",
        data=package_manifest.encode(),
        mime_type="application/json",
    )

    mp4_key: str | None = None
    mp4_hash: str | None = None
    mp4_error: str | None = None
    export_status = "completed"

    # Collect readable image frames from object store (required for MP4 Gate)
    frames_data: list[bytes] = []
    for art in arts:
        if art.artifact_type not in {"image", "export_package"} and not art.mime_type.startswith(
            "image/"
        ):
            continue
        try:
            raw = await obj.get_bytes(object_key=art.object_key)
        except Exception:
            continue
        if raw and (raw[:4] == b"\x89PNG" or art.mime_type.startswith("image/")):
            frames_data.append(raw)

    if try_ffmpeg:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            mp4_error = "FFMPEG_NOT_FOUND"
            # Deliverable package still completed without MP4; MP4 itself not claimed
        elif not frames_data:
            # Fail-closed: do NOT write synthetic black MP4 as success
            mp4_error = "FFMPEG_NO_READABLE_FRAMES"
            export_status = "failed"
            export.error_code = "FFMPEG_NO_READABLE_FRAMES"
            export.error_summary = "no readable image frames for MP4 composition"
        else:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    frame_paths: list[Path] = []
                    for idx, raw in enumerate(frames_data[:20]):
                        fp = tmp_path / f"frame_{idx:03d}.png"
                        fp.write_bytes(raw if raw[:4] == b"\x89PNG" else b"\x89PNG\r\n\x1a\n" + raw)
                        frame_paths.append(fp)
                    out = tmp_path / "program.mp4"
                    list_file = tmp_path / "frames.txt"
                    list_file.write_text(
                        "\n".join(f"file '{f.as_posix()}'\nduration 0.5" for f in frame_paths)
                        + f"\nfile '{frame_paths[-1].as_posix()}'\n",
                        encoding="utf-8",
                    )
                    subprocess.run(
                        [
                            ffmpeg,
                            "-y",
                            "-f",
                            "concat",
                            "-safe",
                            "0",
                            "-i",
                            str(list_file),
                            "-vsync",
                            "vfr",
                            "-pix_fmt",
                            "yuv420p",
                            str(out),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    data = out.read_bytes()
                    mp4_key = f"exports/{project_id}/{export.id}/program.mp4"
                    stored = await obj.put_bytes(
                        object_key=mp4_key, data=data, mime_type="video/mp4"
                    )
                    mp4_hash = stored.content_hash
            except Exception as exc:  # noqa: BLE001
                mp4_error = f"FFMPEG_FAILED: {exc}"[:300]
                export_status = "failed"
                export.error_code = "FFMPEG_FAILED"
                export.error_summary = mp4_error
    else:
        mp4_error = "FFMPEG_SKIPPED"

    # Reuse package artifact by content_hash (reproducible second export)
    existing_pkg = (
        await session.execute(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .where(Artifact.artifact_type == "export_package")
            .where(Artifact.content_hash == package_hash)
        )
    ).scalar_one_or_none()
    if existing_pkg is not None:
        package_art = existing_pkg
    else:
        package_art = Artifact(
            project_id=project_id,
            artifact_type="export_package",
            storage_state="available",
            object_key=f"exports/{project_id}/{export.id}/package.json",
            content_hash=package_hash,
            mime_type="application/json",
            byte_size=len(package_manifest.encode()),
        )
        session.add(package_art)
        await session.flush()

    export.status = export_status
    export.result_artifact_id = package_art.id if export_status == "completed" else None
    export.completed_at = datetime.now(UTC)
    export.manifest = {
        "timeline_hash": timeline_hash,
        "srt_hash": srt_hash,
        "package_hash": package_hash,
        "mp4_hash": mp4_hash,
        "mp4_error": mp4_error,
        "mp4_object_key": mp4_key,
        "item_count": len(arts),
        "export_id": str(export.id),  # metadata only — not in content hashes
    }
    await session.commit()

    return ExportResult(
        export_id=export.id,
        project_id=project_id,
        timeline_json=timeline_json,
        srt=srt,
        package_manifest=package_manifest,
        timeline_hash=timeline_hash,
        srt_hash=srt_hash,
        package_hash=package_hash,
        mp4_object_key=mp4_key,
        mp4_hash=mp4_hash,
        mp4_error=mp4_error,
        source_artifact_ids=[a.id for a in arts],
        source_node_run_ids=[r.id for r in runs],
        export_item_count=len(arts),
        export_status=export_status,
    )
