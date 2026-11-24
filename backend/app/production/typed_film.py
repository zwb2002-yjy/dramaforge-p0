"""Inputs for a source-typed edit in the ordinary local Final Film worker."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.from_artifact_service import MediaSource
from app.editing.models import EditSession
from app.editing.timeline_schema import (
    PublicRenderInput,
    public_render_inputs,
    resolve_public_render_inputs,
)
from app.execution.models import Artifact
from app.production.edit_render_plan import build_render_plan
from app.production.edit_session_render import resolve_render_sources, stage_verified_source
from app.production.session_exports import timeline_hash
from app.production.timeline_renderer import (
    TimelineRenderClip,
    TimelineRenderResult,
    render_timeline,
)
from app.shared.db import set_node_run_rls_context
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore


async def _inputs(
    session: AsyncSession,
    project_id: UUID,
    document: dict[str, Any],
    instructions: list[dict[str, Any]],
) -> tuple[list[PublicRenderInput], dict[UUID, Artifact | MediaSource]]:
    public = public_render_inputs(document)
    checked = await resolve_public_render_inputs(session, project_id, public)
    rows = await resolve_render_sources(session, project_id, instructions, checked)
    for clip in document["clips"]:
        for field in ("selection_snapshot", "audio_selection_snapshot"):
            observed = clip.get(field)
            if not observed or field == "audio_selection_snapshot" and clip.get("muted"):
                continue
            media = rows.get(UUID(observed["artifact_id"]))
            if media is None or media.content_hash != observed.get("artifact_hash"):
                raise ValidationAppError("剪辑选用的媒体已变化，请重新核对")
    music_id = (document.get("metadata") or {}).get("music_artifact_id")
    if music_id:
        music = await session.scalar(
            select(Artifact).where(
                Artifact.id == UUID(str(music_id)),
                Artifact.project_id == project_id,
                Artifact.artifact_type == "audio",
                Artifact.storage_state == "available",
                Artifact.deleted_at.is_(None),
            )
        )
        if music is None:
            raise ValidationAppError("当前项目的背景音乐不可用")
        rows[music.id] = music
    return public, rows


async def freeze_typed_film(session: AsyncSession, edit: EditSession) -> dict[str, str]:
    document = dict(edit.timeline)
    plan = build_render_plan(
        edit_session_id=edit.id,
        timeline_version=edit.version,
        timeline_hash=timeline_hash(document),
        episode_id=edit.episode_id,
        document=document,
    )
    _, rows = await _inputs(
        session, edit.project_id, document, [asdict(c) for c in plan.instructions]
    )
    return {str(media.id): media.content_hash for media in rows.values()}


async def render_typed_film(
    session: AsyncSession,
    project_id: UUID,
    snapshot: dict[str, Any],
    store: ObjectStore,
    directory: Path,
    *,
    max_input_bytes: int,
    max_single_bytes: int,
    node_run_id: UUID,
) -> tuple[TimelineRenderResult, list[dict[str, Any]], list[TimelineRenderClip]]:
    document = snapshot["timeline"]
    if timeline_hash(document) != snapshot.get("timeline_hash"):
        raise ValidationAppError("冻结的剪辑版本不一致")
    plan = build_render_plan(
        edit_session_id=UUID(snapshot["edit_session_id"]),
        timeline_version=snapshot["timeline_version"],
        timeline_hash=snapshot["timeline_hash"],
        episode_id=UUID(snapshot["episode_id"]) if snapshot.get("episode_id") else None,
        document=document,
    )
    instructions = [asdict(c) for c in plan.instructions]
    public, rows = await _inputs(session, project_id, document, instructions)
    if {str(k): v.content_hash for k, v in rows.items()} != snapshot.get("source_hashes"):
        raise ValidationAppError("成片输入已变化")
    if sum(row.byte_size for row in rows.values()) > max_input_bytes or any(
        row.byte_size <= 0 or row.byte_size > max_single_bytes for row in rows.values()
    ):
        raise ValidationAppError("成片输入超出本机处理范围")
    paths: dict[str, Path] = {}
    await session.commit()
    for artifact_id, media in rows.items():
        grants = [g for g in public if g.artifact_id == artifact_id]
        if grants:
            await set_node_run_rls_context(session, node_run_id=node_run_id)
            media = (await resolve_public_render_inputs(session, project_id, grants))[artifact_id]
            await session.commit()
        path = directory / (str(artifact_id) + ".media")
        await stage_verified_source(store, media, path, snapshot["source_hashes"][str(artifact_id)])
        paths[str(artifact_id)] = path
    ordered = sorted(document["clips"], key=lambda c: c["order"])
    clips = [
        TimelineRenderClip(
            **item,
            video_path=paths[item["video_artifact_id"]],
            audio_path=paths.get(item["audio_artifact_id"]),
        )
        for item in instructions
    ]
    lineage = [
        {
            "clip_id": item["id"],
            "source_kind": item["source"]["kind"],
            "source": item["source"],
            "selection_snapshot": item["selection_snapshot"],
            "audio_source": item.get("audio_source"),
            "audio_selection_snapshot": item.get("audio_selection_snapshot"),
            "video_artifact_id": clip.video_artifact_id,
            "audio_artifact_id": clip.audio_artifact_id,
        }
        for item, clip in zip(ordered, clips, strict=True)
    ]
    metadata = document.get("metadata", {})
    rendered = await render_timeline(
        clips,
        lineage=snapshot["timeline_hash"],
        output_path=directory / "final.mp4",
        music_path=paths.get(str(metadata.get("music_artifact_id"))),
        music_volume=float(metadata.get("music_volume", 0.12)),
    )
    return rendered, lineage, clips
