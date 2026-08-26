"""Phase 9 EditingAdapter (03 §82).

create_session / load_timeline / save_timeline / export with edit_sessions
persistence. Production lineage is read-only; editing never mutates the formal
line (Shot.formal_video / Asset.current_version / ProductionGraph).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.editing.models import EditSession
from app.shared.errors import NotFoundError


class EditTimeline:
    """Lightweight timeline shape: ordered clips + edit metadata."""

    def __init__(
        self,
        clips: list[dict[str, object]],
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.clips = clips
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, object]:
        return {"clips": self.clips, "metadata": self.metadata}


class EditingAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        name: str,
        timeline: dict[str, object] | None = None,
        production_lineage: dict[str, object] | None = None,
    ) -> EditSession:
        session_row = EditSession(
            project_id=project_id,
            name=name,
            status="draft",
            timeline=dict(timeline or {"clips": [], "metadata": {}}),
            production_lineage=dict(production_lineage or {}),
            created_by=user_id,
        )
        self._session.add(session_row)
        await self._session.flush()
        return session_row

    async def load_timeline(self, *, project_id: UUID, session_id: UUID) -> EditSession:
        row = await self._session.scalar(
            select(EditSession).where(
                EditSession.id == session_id,
                EditSession.project_id == project_id,
            )
        )
        if row is None:
            raise NotFoundError("edit session not found")
        return row

    async def save_timeline(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        timeline: dict[str, object],
    ) -> EditSession:
        row = await self.load_timeline(project_id=project_id, session_id=session_id)
        row.timeline = dict(timeline)
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def export(self, *, project_id: UUID, session_id: UUID) -> dict[str, object]:
        """Export a render/playback manifest. Production lineage untouched."""
        row = await self.load_timeline(project_id=project_id, session_id=session_id)
        raw_clips = cast(list[object], (row.timeline or {}).get("clips", []))
        clips = [clip for clip in raw_clips if isinstance(clip, dict)]
        total = sum(
            float(clip.get("duration_seconds", 0)) for clip in clips
        )
        return {
            "session_id": str(row.id),
            "format": "dramaforge-edit-v1",
            "clip_count": len(clips),
            "duration_seconds": round(total, 3),
            "clips": clips,
            "production_lineage": row.production_lineage,
        }
