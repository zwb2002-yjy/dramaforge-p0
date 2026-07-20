"""Graph publish service with immutability boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.production.models import (
    GraphVersion,
    ProductionGraph,
    assert_graph_version_mutable,
    definition_hash,
)
from app.shared.enums import GraphStatus
from app.shared.errors import NotFoundError, ValidationAppError


class GraphService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_graph(
        self,
        *,
        project_id: UUID,
        scope_type: str,
        scope_entity_id: UUID,
        template_key: str,
        created_by: UUID,
        definition: dict[str, object] | None = None,
    ) -> ProductionGraph:
        if scope_type not in {"shot", "episode"}:
            raise ValidationAppError("scope_type must be shot or episode")
        body = definition or {"nodes": [], "edges": []}
        graph = ProductionGraph(
            project_id=project_id,
            scope_type=scope_type,
            scope_entity_id=scope_entity_id,
            template_key=template_key,
            status=GraphStatus.DRAFT.value,
            created_by=created_by,
        )
        self._session.add(graph)
        await self._session.flush()
        version = GraphVersion(
            graph_id=graph.id,
            version_number=1,
            status=GraphStatus.DRAFT.value,
            definition_hash=definition_hash(body),
            definition=body,
        )
        self._session.add(version)
        await self._session.flush()
        graph.current_version_id = version.id
        await self._session.flush()
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
        self, *, version_id: UUID, definition: dict[str, object]
    ) -> GraphVersion:
        version = await self.get_version(version_id)
        assert_graph_version_mutable(version)
        version.definition = definition
        version.definition_hash = definition_hash(definition)
        await self._session.flush()
        await self._session.refresh(version)
        return version

    async def publish(self, *, version_id: UUID, published_by: UUID) -> GraphVersion:
        version = await self.get_version(version_id)
        if version.status != GraphStatus.DRAFT.value:
            raise ValidationAppError("only draft versions can be published")
        version.status = GraphStatus.PUBLISHED.value
        version.published_at = datetime.now(UTC)
        version.published_by = published_by
        graph = await self._session.get(ProductionGraph, version.graph_id)
        if graph is not None:
            graph.status = GraphStatus.PUBLISHED.value
            graph.current_version_id = version.id
        await self._session.flush()
        await self._session.refresh(version)
        return version
