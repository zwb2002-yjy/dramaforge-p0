"""Phase 9 EditingAdapter (03 搂82).

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

from app.assets.models import Scene, Shot
from app.editing.models import EditSession
from app.editing.timeline_rules import clip_audio_volume
from app.editing.timeline_schema import (
    declared_schema_version,
    normalize_timeline_for_save,
    public_render_inputs,
    resolve_public_render_inputs,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


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
        episode_id: UUID | None = None,
    ) -> EditSession:
        if episode_id is not None:
            from app.assets.models import Episode

            episode = await self._session.get(Episode, episode_id)
            if episode is None or episode.project_id != project_id:
                raise NotFoundError("episode not found")
        session_row = EditSession(
            project_id=project_id,
            episode_id=episode_id,
            name=name,
            status="draft",
            version=1,
            timeline=dict(timeline or {"clips": [], "metadata": {}}),
            production_lineage=dict(production_lineage or {}),
            created_by=user_id,
        )
        self._session.add(session_row)
        await self._session.flush()
        return session_row

    async def list_sessions(self, *, project_id: UUID) -> list[EditSession]:
        """Discover existing sessions without creating or touching a timeline."""
        rows = await self._session.scalars(
            select(EditSession)
            .where(EditSession.project_id == project_id)
            .order_by(EditSession.updated_at.desc(), EditSession.id.desc())
        )
        return list(rows)

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
        expected_session_version: int,
    ) -> EditSession:
        row = await self._session.scalar(
            select(EditSession)
            .where(
                EditSession.id == session_id,
                EditSession.project_id == project_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("edit session not found")
        if row.version != expected_session_version:
            raise ConflictError(
                "edit session version conflict",
                details={
                    "expected_session_version": expected_session_version,
                    "actual_session_version": row.version,
                },
            )
        if declared_schema_version(timeline) == 1:
            if declared_schema_version(dict(row.timeline or {})) == 2:
                raise ValidationAppError(
                    "a typed timeline must preserve its source schema",
                    details={"code": "EDIT_SCHEMA_DOWNGRADE"},
                )
            if row.episode_id is not None:
                offending = await self._clips_outside_episode(
                    timeline=timeline, episode_id=row.episode_id
                )
                if offending:
                    raise ValidationAppError(
                        "the edit contains clips from another episode",
                        details={"code": "EDIT_CLIP_OUT_OF_EPISODE", "clip_ids": offending},
                    )
        for clip in cast(list[object], timeline.get("clips", [])):
            if isinstance(clip, dict):
                clip_audio_volume(clip)
        # Schema 1 keeps its historical meaning; schema 2 sources are verified
        # against production truth before anything is persisted.
        document = await normalize_timeline_for_save(
            self._session,
            project_id=project_id,
            timeline=timeline,
            episode_id=row.episode_id,
            previous_timeline=dict(row.timeline or {}),
            session_version=row.version + 1,
        )
        row.timeline = dict(document)
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def switch_episode(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        episode_id: UUID | None,
        expected_session_version: int,
    ) -> EditSession:
        """Move a session's episode scope, refusing instead of dropping clips.

        Narrowing to an episode requires every saved clip to come from it. A
        clip that does not belong is reported, never silently removed: the user
        decides whether to delete it explicitly in a versioned Save.
        """
        from app.assets.models import Episode

        row = await self._session.scalar(
            select(EditSession)
            .where(EditSession.id == session_id, EditSession.project_id == project_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("edit session not found")
        if row.version != expected_session_version:
            raise ConflictError(
                "edit session version conflict",
                details={
                    "expected_session_version": expected_session_version,
                    "actual_session_version": row.version,
                },
            )
        if episode_id is not None:
            episode = await self._session.get(Episode, episode_id)
            if episode is None or episode.project_id != project_id:
                raise NotFoundError("episode not found")
        if row.episode_id == episode_id:
            return row
        if episode_id is not None:
            offending = await self._clips_outside_episode(
                timeline=dict(row.timeline or {}), episode_id=episode_id
            )
            if offending:
                raise ValidationAppError(
                    "saved clips belong to another episode; delete them explicitly first",
                    details={
                        "code": "EDIT_SCOPE_SWITCH_REJECTED",
                        "clip_ids": offending,
                        "target_episode_id": str(episode_id),
                    },
                )
        row.episode_id = episode_id
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def _clips_outside_episode(
        self, *, timeline: dict[str, object], episode_id: UUID
    ) -> list[str]:
        """Clip ids whose shot is not in the target episode (schema 1 or 2)."""
        raw_clips = timeline.get("clips")
        if not isinstance(raw_clips, list):
            return []
        offending: list[str] = []
        for raw in raw_clips:
            if not isinstance(raw, dict):
                continue
            clip_id = str(raw.get("id") or "")
            source = raw.get("source")
            shot_value = raw.get("shot_id")
            if isinstance(source, dict):
                if declared_schema_version(timeline) == 1:
                    offending.append(clip_id)
                    continue
                if source.get("kind") != "shot_formal":
                    # Adopted asset versions and public material are not
                    # episode-bound; they stay usable in any episode.
                    continue
                shot_value = source.get("shot_id")
            if not isinstance(shot_value, str):
                offending.append(clip_id)
                continue
            try:
                shot_id = UUID(shot_value)
            except ValueError:
                offending.append(clip_id)
                continue
            belongs = await self._session.scalar(
                select(Shot.id)
                .join(Scene, Scene.id == Shot.scene_id)
                .where(Shot.id == shot_id, Scene.episode_id == episode_id)
            )
            if belongs is None:
                offending.append(clip_id)
        return offending

    async def export(self, *, project_id: UUID, session_id: UUID) -> dict[str, object]:
        """Export a render/playback manifest. Production lineage untouched."""
        row = await self.load_timeline(project_id=project_id, session_id=session_id)
        await resolve_public_render_inputs(
            self._session, project_id,
            public_render_inputs(dict(row.timeline or {}), include_muted=True),
        )
        raw_clips = cast(list[object], (row.timeline or {}).get("clips", []))
        clips = [clip for clip in raw_clips if isinstance(clip, dict)]
        total = sum(float(clip.get("duration_seconds", 0)) for clip in clips)
        return {
            "session_id": str(row.id),
            "format": "dramaforge-edit-v1",
            "clip_count": len(clips),
            "duration_seconds": round(total, 3),
            "clips": clips,
            "production_lineage": row.production_lineage,
        }
