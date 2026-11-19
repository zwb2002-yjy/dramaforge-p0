"""Session exports bind one immutable timeline snapshot (I9-02).

Creating an export freezes the session's current version and the hash of that
exact document, then binds one item per clip to the frozen media artifact. A
later edit never changes an existing export: it is a receipt of one version, and
a repeated idempotency key returns the original export instead of re-binding it.

Rendering MP4/SRT is deliberately not implemented here: that step needs a real
render run and is gated by the contract's generation rules, so an export asking
for it is refused rather than silently queued without a render.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.shared.errors import NotFoundError, ValidationAppError

# Only snapshot formats that need no new media generation are allowed here.
SNAPSHOT_FORMATS: frozenset[str] = frozenset({"timeline_json"})
RENDER_FORMATS: frozenset[str] = frozenset({"mp4", "srt"})


def timeline_hash(timeline: dict[str, Any]) -> str:
    encoded = json.dumps(timeline, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clip_source_artifact(clip: dict[str, Any]) -> UUID | None:
    """Frozen artifact identity of one clip, if the saved document names one."""
    source = clip.get("source")
    if isinstance(source, dict):
        snapshot = clip.get("selection_snapshot")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("artifact_id"), str):
            return UUID(str(snapshot["artifact_id"]))
        return None
    raw = clip.get("artifact_id")
    return UUID(str(raw)) if isinstance(raw, str) else None


class ExportService:
    """Caller establishes project ownership first; commit stays with the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session_export(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        requested_by: UUID,
        format: str = "timeline_json",
        idempotency_key: str | None = None,
    ) -> tuple[Export, bool]:
        if format in RENDER_FORMATS:
            raise ValidationAppError(
                "this export needs a bound render run before it can be created",
                details={"code": "EXPORT_RENDER_REQUIRED", "format": format},
            )
        if format not in SNAPSHOT_FORMATS:
            raise ValidationAppError(
                "unsupported export format",
                details={"code": "EXPORT_FORMAT_UNSUPPORTED", "format": format},
            )
        if idempotency_key is not None:
            existing = await self._session.scalar(
                select(Export).where(
                    Export.project_id == project_id,
                    Export.format == format,
                    Export.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                # Receipt priority: never re-bind a newer timeline over a receipt.
                return existing, False
        edit_session = await self._session.scalar(
            select(EditSession).where(
                EditSession.id == session_id, EditSession.project_id == project_id
            )
        )
        if edit_session is None:
            raise NotFoundError("edit session not found")
        document = dict(edit_session.timeline or {})
        clips = _clips_of(document)
        items: list[tuple[int, UUID, str, dict[str, Any]]] = []
        for ordinal, clip in enumerate(clips, start=1):
            artifact_id = _clip_source_artifact(clip)
            if artifact_id is None:
                raise ValidationAppError(
                    "clip has no frozen artifact to export",
                    details={
                        "code": "EXPORT_CLIP_UNBOUND",
                        "clip_id": str(clip.get("id") or ""),
                        "ordinal": ordinal,
                    },
                )
            items.append(
                (
                    ordinal,
                    artifact_id,
                    "video",
                    {
                        "clip_id": str(clip.get("id") or ""),
                        "timeline_version": edit_session.version,
                    },
                )
            )
        export = Export(
            project_id=project_id,
            episode_id=edit_session.episode_id,
            format=format,
            status="queued",
            requested_by=requested_by,
            manifest={
                "schema_version": document.get("schema_version", 1),
                "edit_session_id": str(edit_session.id),
                "timeline_version": edit_session.version,
                "timeline_hash": timeline_hash(document),
                "episode_id": str(edit_session.episode_id) if edit_session.episode_id else None,
                "clip_count": len(items),
            },
            edit_session_id=edit_session.id,
            timeline_version=edit_session.version,
            timeline_hash=timeline_hash(document),
            idempotency_key=idempotency_key,
        )
        self._session.add(export)
        await self._session.flush()
        for ordinal, artifact_id, role, metadata in items:
            self._session.add(
                ExportItem(
                    export_id=export.id,
                    ordinal=ordinal,
                    source_artifact_id=artifact_id,
                    role=role,
                    metadata_json=metadata,
                )
            )
        await self._session.flush()
        return export, True

    async def items_of(self, *, export_id: UUID) -> list[ExportItem]:
        rows = await self._session.scalars(
            select(ExportItem).where(ExportItem.export_id == export_id).order_by(ExportItem.ordinal)
        )
        return list(rows)


def _clips_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("clips")
    if not isinstance(raw, list):
        return []
    return [clip for clip in raw if isinstance(clip, dict)]


__all__ = [
    "RENDER_FORMATS",
    "SNAPSHOT_FORMATS",
    "ExportService",
    "timeline_hash",
]
