"""Authorized, bounded story reads used by the Director's read-only tools."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.asset_card_service import AssetCardReadService
from app.assets.models import Asset, Episode, Scene, Shot
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError


class AgentReadService:
    """Own project authorization and bounded queries; never write domain rows."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
    ) -> None:
        self._session = session
        self._actor_id = actor_id
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._actor: User | None = None

    async def project(self) -> Project:
        self._session.info["selected_workspace_id"] = self._workspace_id
        await set_rls_context(
            self._session,
            user_id=self._actor_id,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
        )
        actor = await self._session.get(User, self._actor_id)
        if actor is None or not actor.is_active:
            raise NotFoundError("actor not found")
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=self._project_id,
            actor=actor,
        )
        self._actor = actor
        return project

    async def scenes(self, *, limit: int, offset: int) -> list[Scene]:
        await self.project()
        rows = await self._session.scalars(
            select(Scene)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Episode.project_id == self._project_id)
            .order_by(Episode.episode_number, Scene.scene_number, Scene.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def scene(self, scene_id: UUID) -> Scene:
        await self.project()
        row = await self._session.scalar(
            select(Scene)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Scene.id == scene_id, Episode.project_id == self._project_id)
        )
        if row is None:
            raise NotFoundError("scene not found")
        return row

    async def shots(self, *, scene_id: UUID, limit: int, offset: int) -> list[Shot]:
        await self.scene(scene_id)
        rows = await self._session.scalars(
            select(Shot)
            .where(Shot.project_id == self._project_id, Shot.scene_id == scene_id)
            .order_by(Shot.sort_order, Shot.shot_number, Shot.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def shot(self, shot_id: UUID) -> Shot:
        await self.project()
        row = await self._session.scalar(
            select(Shot).where(
                Shot.id == shot_id,
                Shot.project_id == self._project_id,
            )
        )
        if row is None:
            raise NotFoundError("shot not found")
        return row

    async def assets(self, *, limit: int, offset: int) -> list[Asset]:
        await self.project()
        rows = await self._session.scalars(
            select(Asset)
            .where(Asset.project_id == self._project_id, Asset.status != "recycled")
            .order_by(Asset.kind, Asset.name, Asset.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def asset(self, asset_id: UUID) -> dict[str, object]:
        await self.project()
        assert self._actor is not None
        return await AssetCardReadService(self._session).read_card(
            project_id=self._project_id,
            asset_id=asset_id,
            actor=self._actor,
        )
