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
from uuid import UUID

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
    graph_version_id: UUID | None = None,
    approved_shot_ids: list[UUID] | None = None,
    require_approved: bool = True,
    exact_artifact_ids: list[UUID] | None = None,
    exact_node_run_ids: list[UUID] | None = None,
) -> ExportResult:
    """Export deliverables.

    Formal path: only Artifacts from completed NodeRuns under optional GraphVersion,
    and only for approved (review_passed) shots when require_approved and shots exist.
    """
    from app.assets.models import Shot

    exact = exact_artifact_ids is not None or exact_node_run_ids is not None
    if exact_artifact_ids is None or exact_node_run_ids is None:
        if exact:
            raise ValidationAppError(
                "exact export requires paired artifact and NodeRun identifiers"
            )
    elif (
        not exact_artifact_ids
        or len(exact_artifact_ids) != len(exact_node_run_ids)
        or len(set(exact_artifact_ids)) != len(exact_artifact_ids)
        or len(set(exact_node_run_ids)) != len(exact_node_run_ids)
    ):
        raise ValidationAppError("exact export lineage is empty, duplicated, or unpaired")
    if exact and (graph_version_id is not None or approved_shot_ids is not None):
        raise ValidationAppError("exact export cannot be combined with legacy export filters")

    approved_ids: set[UUID] | None = None
    if exact:
        approved_ids = None
    elif approved_shot_ids is not None:
        approved_ids = set(approved_shot_ids)
        if require_approved and not approved_ids:
            raise ValidationAppError(
                "EXPORT_GATE: approved_shot_ids is empty; refuse export of unreviewed work"
            )
    elif require_approved:
        approved_rows = list(
            (
                await session.execute(
                    select(Shot).where(
                        Shot.project_id == project_id,
                        Shot.status == "review_passed",
                    )
                )
            )
            .scalars()
            .all()
        )
        # Fail closed: zero review_passed must NOT export all completed artifacts.
        if not approved_rows:
            raise ValidationAppError(
                "EXPORT_GATE: no shot with status=review_passed; "
                "approve shots before formal export"
            )
        approved_ids = {s.id for s in approved_rows}

    run_q = select(NodeRun).where(NodeRun.project_id == project_id)
    if exact:
        assert exact_node_run_ids is not None
        run_q = run_q.where(NodeRun.id.in_(exact_node_run_ids))
    else:
        run_q = run_q.where(
            NodeRun.status.in_(("completed", "cached", "completed_after_cancel"))
        )
        if graph_version_id is not None:
            run_q = run_q.where(NodeRun.graph_version_id == graph_version_id)
    raw_runs = list((await session.execute(run_q)).scalars().all())
    if exact:
        assert exact_node_run_ids is not None
        run_by_id = {run.id: run for run in raw_runs}
        missing_runs = [value for value in exact_node_run_ids if value not in run_by_id]
        if missing_runs:
            raise ValidationAppError("exact export NodeRun lineage is incomplete")
        runs = [run_by_id[value] for value in exact_node_run_ids]
        if any(
            run.status not in {"completed", "cached", "completed_after_cancel"}
            for run in runs
        ):
            raise ValidationAppError("exact export contains a non-terminal NodeRun")
    else:
        runs = raw_runs

    if approved_ids is not None:
        filtered_runs: list[NodeRun] = []
        for r in runs:
            snap = r.input_snapshot or {}
            sid = snap.get("shot_id")
            if sid is None:
                continue
            try:
                if UUID(str(sid)) in approved_ids:
                    filtered_runs.append(r)
            except Exception:
                continue
        runs = filtered_runs

    run_ids = {r.id for r in runs}
    art_q = (
        select(Artifact)
        .where(Artifact.project_id == project_id)
        .where(Artifact.storage_state == "available")
        .where(Artifact.deleted_at.is_(None))
        .where(Artifact.artifact_type != "export_package")
    )
    if exact:
        assert exact_artifact_ids is not None
        art_q = art_q.where(Artifact.id.in_(exact_artifact_ids))
    raw_arts = list(
        (
            await session.execute(art_q)
        )
        .scalars()
        .all()
    )
    if exact:
        assert exact_artifact_ids is not None
        assert exact_node_run_ids is not None
        artifact_by_id = {artifact.id: artifact for artifact in raw_arts}
        missing_artifacts = [
            value for value in exact_artifact_ids if value not in artifact_by_id
        ]
        if missing_artifacts:
            raise ValidationAppError("exact export artifact lineage is incomplete")
        arts = [artifact_by_id[value] for value in exact_artifact_ids]
        if any(
            artifact.produced_by_run_id != run_id
            for artifact, run_id in zip(arts, exact_node_run_ids, strict=True)
        ):
            raise ValidationAppError("exact export artifact/NodeRun lineage does not match")
    else:
        arts = raw_arts
    if approved_ids is not None:
        # Keep artifacts from approved-shot NodeRuns + audited manual uploads for those shots
        kept: list[Artifact] = []
        for a in arts:
            if a.produced_by_run_id is not None and a.produced_by_run_id in run_ids:
                kept.append(a)
                continue
            reason = a.delete_reason or ""
            if "audited_manual_upload" in reason and any(
                str(sid) in reason or str(sid) in a.object_key
                for sid in approved_ids
            ):
                # object_key / reason includes shot id
                kept.append(a)
        arts = kept
    elif run_ids:
        arts = [a for a in arts if a.produced_by_run_id in run_ids]
    if not arts:
        raise ValidationAppError(
            "no available artifacts to export "
            "(need completed NodeRuns or audited manual media for approved shots)"
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
    # Prefer real video/voice/composite artifacts for timeline; fall back to images
    media_arts = [
        a
        for a in arts
        if a.artifact_type in {"video", "composite", "voice", "subtitle", "image", "manual_media"}
        or a.mime_type.startswith(("video/", "audio/", "image/"))
    ]
    if not media_arts:
        media_arts = arts

    timeline_body = content_timeline(
        project_id=project_id,
        shot_subtitles=subs,
        artifact_hashes=[a.content_hash for a in media_arts],
        node_run_ids=[str(r.id) for r in runs],
    )
    if graph_version_id is not None:
        timeline_body["graph_version_id"] = str(graph_version_id)
    timeline_json = json.dumps(timeline_body, sort_keys=True, separators=(",", ":"))
    # SRT: 2s per line from real dialogue list (not fixed 0.5s stub for all)
    srt_lines: list[str] = []
    t = 0
    for i, (_sid, text) in enumerate(subs, start=1):
        start_s, end_s = t, t + 2
        srt_lines.append(
            f"{i}\n"
            f"00:00:{start_s:02d},000 --> 00:00:{end_s:02d},000\n"
            f"{text}\n"
        )
        t = end_s
    srt = "\n".join(srt_lines)
    package_body = content_package(
        project_id=project_id,
        items=[
            {
                "content_hash": a.content_hash,
                "mime_type": a.mime_type,
                "byte_size": a.byte_size,
                "artifact_type": a.artifact_type,
                "object_key": a.object_key,
            }
            for a in media_arts
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
    # Material package: include real media file bytes under media/ + manifest
    import zipfile
    from io import BytesIO

    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.json", package_manifest)
        zf.writestr("timeline.json", timeline_json)
        zf.writestr("subtitles.srt", srt)
        for a in media_arts:
            try:
                raw = await obj.get_bytes(object_key=a.object_key)
            except Exception:
                continue
            name = a.object_key.split("/")[-1] or f"{a.content_hash[:12]}.bin"
            zf.writestr(f"media/{name}", raw)
    package_zip = zip_buf.getvalue()
    package_zip_hash = hashlib.sha256(package_zip).hexdigest()
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export.id}/package.json",
        data=package_manifest.encode(),
        mime_type="application/json",
    )
    await obj.put_bytes(
        object_key=f"exports/{project_id}/{export.id}/package.zip",
        data=package_zip,
        mime_type="application/zip",
    )
    package_hash = package_zip_hash

    mp4_key: str | None = None
    mp4_hash: str | None = None
    mp4_error: str | None = None
    export_status = "completed"

    # Prefer real video bytes for MP4; else compose from image/composite frames
    video_blobs: list[bytes] = []
    frames_data: list[bytes] = []
    for art in media_arts:
        try:
            raw = await obj.get_bytes(object_key=art.object_key)
        except Exception:
            continue
        if not raw:
            continue
        video_candidate = art.mime_type.startswith("video/") or art.artifact_type in {
            "video",
            "composite",
        }
        has_video_signature = (
            raw[:4] == b"\x00\x00\x00"
            or raw[4:8] == b"ftyp"
            or raw[:3] == b"\x00\x00\x00"
            or art.mime_type.startswith("video/")
        )
        if video_candidate and has_video_signature:
            # composite may be image in fake tests — detect
            video_blobs.append(raw)
        if art.mime_type.startswith("image/") or raw[:4] == b"\x89PNG":
            frames_data.append(raw)

    if try_ffmpeg:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            mp4_error = "FFMPEG_NOT_FOUND"
        elif video_blobs:
            # Prefer concatenating real video segment bytes (composite/video artifacts)
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    parts: list[Path] = []
                    for idx, raw in enumerate(video_blobs[:20]):
                        # Detect ftyp/mp4 vs treat as copyable segment
                        is_mp4 = (
                            raw[4:8] == b"ftyp"
                            or raw[:4] == b"\x00\x00\x00\x18"
                            or b"ftyp" in raw[:64]
                        )
                        ext = "mp4" if is_mp4 else "bin"
                        p = tmp_path / f"seg_{idx:03d}.{ext}"
                        p.write_bytes(raw)
                        parts.append(p)
                    out = tmp_path / "program.mp4"
                    if len(parts) == 1 and parts[0].suffix == ".mp4":
                        # Single real video segment — copy as deliverable
                        out.write_bytes(parts[0].read_bytes())
                    else:
                        list_file = tmp_path / "videos.txt"
                        list_file.write_text(
                            "\n".join(f"file '{p.as_posix()}'" for p in parts) + "\n",
                            encoding="utf-8",
                        )
                        # Try stream copy first; re-encode if needed
                        concat_process = subprocess.run(
                            [
                                ffmpeg,
                                "-y",
                                "-f",
                                "concat",
                                "-safe",
                                "0",
                                "-i",
                                str(list_file),
                                "-c",
                                "copy",
                                str(out),
                            ],
                            capture_output=True,
                        )
                        if (
                            concat_process.returncode != 0
                            or not out.exists()
                            or out.stat().st_size < 32
                        ):
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
                                    "-c:v",
                                    "libx264",
                                    "-pix_fmt",
                                    "yuv420p",
                                    "-c:a",
                                    "aac",
                                    str(out),
                                ],
                                check=True,
                                capture_output=True,
                            )
                    data = out.read_bytes()
                    if len(data) < 32:
                        raise RuntimeError("mp4 output too small")
                    mp4_key = f"exports/{project_id}/{export.id}/program.mp4"
                    stored = await obj.put_bytes(
                        object_key=mp4_key, data=data, mime_type="video/mp4"
                    )
                    mp4_hash = stored.content_hash
            except Exception as exc:  # noqa: BLE001
                mp4_error = f"FFMPEG_VIDEO_FAILED: {exc}"[:300]
                export_status = "failed"
                export.error_code = "FFMPEG_VIDEO_FAILED"
                export.error_summary = mp4_error
        elif frames_data:
            # Image-only composition is allowed only as last resort when no video
            # artifacts exist; duration uses 2s per frame (not 0.5s stub slideshow).
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    frame_paths: list[Path] = []
                    for idx, raw in enumerate(frames_data[:20]):
                        fp = tmp_path / f"frame_{idx:03d}.png"
                        if raw[:4] == b"\x89PNG":
                            fp.write_bytes(raw)
                        else:
                            # require real PNG; skip non-image garbage
                            continue
                        frame_paths.append(fp)
                    if not frame_paths:
                        raise RuntimeError("no valid PNG frames")
                    out = tmp_path / "program.mp4"
                    list_file = tmp_path / "frames.txt"
                    list_file.write_text(
                        "\n".join(f"file '{f.as_posix()}'\nduration 2.0" for f in frame_paths)
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
                    # Annotate that this is image-derived when no video nodes
                    export.error_summary = "mp4_from_image_frames_no_video_artifacts"
            except Exception as exc:  # noqa: BLE001
                mp4_error = f"FFMPEG_FAILED: {exc}"[:300]
                export_status = "failed"
                export.error_code = "FFMPEG_FAILED"
                export.error_summary = mp4_error
        else:
            mp4_error = "FFMPEG_NO_MEDIA"
            export_status = "failed"
            export.error_code = "FFMPEG_NO_MEDIA"
            export.error_summary = "no video or image artifacts for MP4"
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
    # Artifact metadata must match the ZIP body (hash/mime/size/object_key), not package.json.
    package_zip_key = f"exports/{project_id}/{export.id}/package.zip"
    if existing_pkg is not None:
        package_art = existing_pkg
    else:
        package_art = Artifact(
            project_id=project_id,
            artifact_type="export_package",
            storage_state="available",
            object_key=package_zip_key,
            content_hash=package_zip_hash,
            mime_type="application/zip",
            byte_size=len(package_zip),
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
