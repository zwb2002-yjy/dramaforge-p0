"""S5 local export metadata package (hashable; no live FFmpeg required)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ExportPackage:
    export_id: UUID
    project_id: UUID
    timeline_json: str
    srt: str
    timeline_hash: str
    srt_hash: str
    mp4_placeholder_key: str


def build_export_package(
    *,
    project_id: UUID,
    shots: list[dict[str, object]],
) -> ExportPackage:
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
    )
