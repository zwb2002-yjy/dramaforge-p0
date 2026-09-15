"""P1-01 workspace state persistence and restore for the professional shell."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User, UserProjectPreference
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.shared.errors import ValidationAppError

# The only workspace-state keys that name another project's data.  Everything
# else in the object describes this user's own view (last_view, panels, ...) and
# is stored verbatim.
_SELECTION_KEYS: dict[str, str] = {
    "selected_scene_id": "scene",
    "selected_shot_id": "shot",
}


class WorkspaceStateService:
    """Per-user project workspace state used for last-view restore and panels.

    The state is a JSON object on ``UserProjectPreference``; patches merge into
    the existing object so the frontend can persist view/shot/panel facts
    independently without a second source of truth.

    Selection values are reconciled against this project on both read and write:
    a client may clear a selection, but it may not persist an ID that belongs to
    another project, and a selection whose Scene or Shot no longer belongs to the
    project is dropped instead of being replayed as a stale pointer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_preference(self, *, project_id: UUID, actor: User) -> UserProjectPreference:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        result = await self._session.execute(
            select(UserProjectPreference).where(
                UserProjectPreference.user_id == actor.id,
                UserProjectPreference.project_id == project_id,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = UserProjectPreference(
                user_id=actor.id,
                project_id=project_id,
            )
            self._session.add(pref)
            await self._session.flush()
        return pref

    async def _validate_selection(self, *, project_id: UUID, key: str, raw: object) -> None:
        """Reject a selection that names another project's Scene or Shot.

        ``None`` and ``""`` are explicit clears.  Any other value must be a
        non-empty string that names an entity of *this* project; a missing or
        malformed value is a client bug rather than a silent no-op, because
        accepting it would persist a pointer this project can never resolve.
        """
        if raw is None or raw == "":
            return
        if not isinstance(raw, str):
            raise ValidationAppError(
                f"{key} must be a UUID string or null",
                details={"code": "WORKSPACE_STATE_SELECTION_INVALID", "field": key},
            )
        try:
            entity_id = UUID(raw)
        except ValueError as exc:
            raise ValidationAppError(
                f"{key} must be a UUID string or null",
                details={"code": "WORKSPACE_STATE_SELECTION_INVALID", "field": key},
            ) from exc
        entity = _SELECTION_KEYS[key]
        if entity == "scene":
            owned = await self._session.scalar(
                select(Scene.id)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Scene.id == entity_id, Episode.project_id == project_id)
            )
        else:
            owned = await self._session.scalar(
                select(Shot.id).where(Shot.id == entity_id, Shot.project_id == project_id)
            )
        if owned is None:
            raise ValidationAppError(
                f"{key} does not belong to this project",
                details={
                    "code": "WORKSPACE_STATE_SELECTION_FOREIGN",
                    "field": key,
                    "entity": entity,
                },
            )

    async def _reconcile(self, *, project_id: UUID, state: dict[str, object]) -> dict[str, object]:
        """Drop selections this project can no longer resolve.

        Applies to reads as well as writes: a Scene or Shot deleted after the
        state was stored must not come back as a restore pointer.
        """
        cleaned = dict(state)
        for key in _SELECTION_KEYS:
            raw = cleaned.get(key)
            if raw is None or raw == "":
                continue
            try:
                entity_id = UUID(str(raw))
            except ValueError:
                cleaned.pop(key, None)
                continue
            if _SELECTION_KEYS[key] == "scene":
                owned = await self._session.scalar(
                    select(Scene.id)
                    .join(Episode, Episode.id == Scene.episode_id)
                    .where(Scene.id == entity_id, Episode.project_id == project_id)
                )
            else:
                owned = await self._session.scalar(
                    select(Shot.id).where(Shot.id == entity_id, Shot.project_id == project_id)
                )
            if owned is None:
                cleaned.pop(key, None)
        return cleaned

    async def get_workspace_state(self, *, project_id: UUID, actor: User) -> dict[str, object]:
        pref = await self._get_preference(project_id=project_id, actor=actor)
        stored = dict(pref.workspace_state or {})
        cleaned = await self._reconcile(project_id=project_id, state=stored)
        if cleaned != stored:
            pref.workspace_state = cleaned
            await self._session.flush()
        return cleaned

    async def update_workspace_state(
        self,
        *,
        project_id: UUID,
        actor: User,
        state: dict[str, object],
    ) -> dict[str, object]:
        if not isinstance(state, dict):
            raise ValidationAppError("workspace state must be a JSON object")
        pref = await self._get_preference(project_id=project_id, actor=actor)
        for key in _SELECTION_KEYS:
            if key in state:
                await self._validate_selection(project_id=project_id, key=key, raw=state[key])
        merged = dict(pref.workspace_state or {})
        merged.update(state)
        pref.workspace_state = merged
        await self._session.flush()
        return dict(pref.workspace_state)
