"""Graph publish service with immutability boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.production.models import Graph, GraphVersion, assert_graph_version_mutable
from app.shared.enums import GraphStatus
from app.shared.errors import NotFoundError, ValidationAppError


class GraphService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_graph(self, *, project_id: UUID, name: str) -> Graph:
        graph = Graph(project_id=project_id, name=name)
        self._session.add(graph)
        await self._session.flush()
        version = GraphVersion(
            graph_id=graph.id,
            version=1,
            status=GraphStatus.DRAFT.value,
            definition={"nodes": [], "edges": []},
        )
        self._session.add(version)
        await self._session.commit()
        await self._session.refresh(graph)
        return graph

    async def get_version(self, version_id: UUID) -> GraphVersion:
        result = await self._session.execute(
            select(GraphVersion).where(GraphVersion.id == version_id)
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise NotFoundError("graph version not found")
        return version

    async def update_draft_definition(
        self, *, version_id: UUID, definition: dict
    ) -> GraphVersion:
        version = await self.get_version(version_id)
        assert_graph_version_mutable(version)
        version.definition = definition
        await self._session.commit()
        await self._session.refresh(version)
        return version

    async def publish(self, *, version_id: UUID) -> GraphVersion:
        version = await self.get_version(version_id)
        if version.status != GraphStatus.DRAFT.value:
            raise ValidationAppError("only draft versions can be published")
        version.status = GraphStatus.PUBLISHED.value
        version.published_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(version)
        return version
