"""S5 export package from completed NodeRun artifacts (hashable metadata)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact


@dataclass(frozen=True)
class ExportPackage:
    export_id: UUID
    project_id: UUID
    timeline_json: str
    srt: str
    timeline_hash: str
    srt_hash: str
    mp4_placeholder_key: str
    source_artifact_ids: list[UUID]


async def build_export_from_runs(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_subtitles: list[tuple[str, str]],
) -> ExportPackage:
    """Build timeline/SRT from project artifacts; sources are real Artifact rows when present."""
    result = await session.execute(
        select(Artifact).where(Artifact.project_id == project_id).where(
            Artifact.storage_state == "available"
        )
    )
    artifacts = list(result.scalars().all())
    timeline = {
        "version": "timeline-p0-v1",
        "project_id": str(project_id),
        "shots": [
            {"id": sid, "subtitle": sub, "artifact_count": len(artifacts)}
            for sid, sub in shot_subtitles
        ],
        "artifact_hashes": [a.content_hash for a in artifacts],
    }
    timeline_json = json.dumps(timeline, sort_keys=True, separators=(",", ":"))
    srt_lines: list[str] = []
    for i, (_sid, text) in enumerate(shot_subtitles, start=1):
        srt_lines.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n{text}\n")
    srt = "\n".join(srt_lines)
    return ExportPackage(
        export_id=uuid4(),
        project_id=project_id,
        timeline_json=timeline_json,
        srt=srt,
        timeline_hash=hashlib.sha256(timeline_json.encode()).hexdigest(),
        srt_hash=hashlib.sha256(srt.encode()).hexdigest(),
        mp4_placeholder_key=f"exports/{project_id}/program.mp4",
        source_artifact_ids=[a.id for a in artifacts],
    )


def build_export_package(
    *,
    project_id: UUID,
    shots: list[dict[str, object]],
) -> ExportPackage:
    """Sync helper for pure hash tests without session."""
    timeline = {
        "version": "timeline-p0-v1",
        "project_id": str(project_id),
        "shots": shots,
    }
    timeline_json = json.dumps(timeline, sort_keys=True, separators=(",", ":"))
    srt_lines: list[str] = []
    for i, shot in enumerate(shots, start=1):
        text = str(shot.get("subtitle", ""))
        srt_lines.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n{text}\n")
    srt = "\n".join(srt_lines)
    return ExportPackage(
        export_id=uuid4(),
        project_id=project_id,
        timeline_json=timeline_json,
        srt=srt,
        timeline_hash=hashlib.sha256(timeline_json.encode()).hexdigest(),
        srt_hash=hashlib.sha256(srt.encode()).hexdigest(),
        mp4_placeholder_key=f"exports/{project_id}/program.mp4",
        source_artifact_ids=[],
    )
