"""End-to-end golden sample: import script → character → 10-shot Graph → export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.characters import register_lead_character
from app.assets.models import Shot
from app.assets.script_import import import_script
from app.delivery.export_service import ExportResult, build_project_export
from app.execution.shot_p0 import ShotRecord, produce_shots_p0
from app.providers.fake import FakeFluxAdapter
from app.storage.minio_store import ObjectStore, get_object_store

REPO_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "scripts" / "p0_10_shots.md"


@dataclass(frozen=True)
class GoldenPathResult:
    script_document_id: UUID
    episode_id: UUID
    character_id: UUID
    canonical_object_key: str
    shot_count: int
    shots: list[ShotRecord]
    export: ExportResult
    content_hash: str


async def run_golden_p0_path(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    script_text: str | None = None,
    script_path: Path | None = None,
    store: ObjectStore | None = None,
    try_ffmpeg: bool = False,
) -> GoldenPathResult:
    """Run closable §3.1 spine from frozen fixture (fake adapters)."""
    obj = store or get_object_store()
    text = script_text
    if text is None:
        path = script_path or REPO_FIXTURE
        text = path.read_text(encoding="utf-8")
    imp = await import_script(
        session,
        project_id=project_id,
        actor_id=user_id,
        filename="p0_10_shots.md",
        text=text,
    )
    lead = imp.lead_character or "Lead"
    ad = FakeFluxAdapter()
    created = await ad.create({"prompt": f"canonical {lead}", "kind": "keyframe"})
    canon_bytes = ad.blobs[created["remote_task_id"]]
    char = await register_lead_character(
        session,
        project_id=project_id,
        name=lead,
        locked_prompt=f"{lead} locked prompt",
        canonical_image_bytes=canon_bytes,
        store=obj,
    )
    rows = list(
        (
            await session.execute(
                select(Shot)
                .where(Shot.project_id == project_id)
                .order_by(Shot.sort_order)
            )
        )
        .scalars()
        .all()
    )
    specs = [(r.id, r.visual_description, r.dialogue or f"Line {r.sort_order}") for r in rows]
    produced = await produce_shots_p0(
        session,
        project_id=project_id,
        user_id=user_id,
        n=len(specs),
        store=obj,
        shot_specs=specs,
        shared_canonical_object_key=char.canonical_object_key,
        shared_canonical_bytes=canon_bytes,
    )
    subs = [(str(s.shot_id), s.subtitle) for s in produced]
    exp = await build_project_export(
        session,
        project_id=project_id,
        requested_by=user_id,
        shot_subtitles=subs,
        store=obj,
        try_ffmpeg=try_ffmpeg,
    )
    return GoldenPathResult(
        script_document_id=imp.script_document_id,
        episode_id=imp.episode_id,
        character_id=char.character_id,
        canonical_object_key=char.canonical_object_key,
        shot_count=len(produced),
        shots=produced,
        export=exp,
        content_hash=imp.content_hash,
    )
