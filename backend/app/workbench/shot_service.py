"""P1-03 shot design updates with optimistic concurrency."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class ShotDesignService:
    """Write structured director intent and free-text prompts for a shot.

    The update is an optimistic, user-initiated edit: it validates the shot
    belongs to the project, compares ``Shot.version``, writes the new design
    facts, and bumps ``Shot.version``. It never generates media and never
    requires an explicit user save before execution (Phase 1 boundary).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_shot_design(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        actor: User,
        expected_version: int,
        director_state: dict[str, object] | None = None,
        image_prompt: str | None = None,
        video_prompt: str | None = None,
    ) -> Shot:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        shot = (
            await self._session.execute(
                select(Shot)
                .where(Shot.id == shot_id, Shot.project_id == project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if shot is None:
            raise NotFoundError("shot not found")
        if shot.version != expected_version:
            raise ConflictError(
                "shot version conflict",
                details={
                    "expected_version": expected_version,
                    "actual_version": shot.version,
                },
            )
        if director_state is not None:
            if not isinstance(director_state, dict):
                raise ValidationAppError("director_state must be a JSON object")
            shot.director_state = dict(director_state)
        if image_prompt is not None:
            shot.image_prompt = image_prompt
        if video_prompt is not None:
            shot.video_prompt = video_prompt
        shot.version += 1
        shot.updated_at = datetime.now(UTC)
        await self._session.flush()
        return shot
