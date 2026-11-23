"""The project's two explicitly dispatched delivery nodes share its scoped graph."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.production.models import ProductionGraph
from app.production.service import GraphService, MaterializedGraph
from app.shared.errors import ConflictError

FINAL_FILM_NODE = "final_film_assembly"
EDIT_RENDER_NODE = "edit_session_render"
FINAL_FILM_FORMAT = "dramaforge-final-film-v1"
_NODES = {
    FINAL_FILM_NODE: "Final Film Timeline Render",
    EDIT_RENDER_NODE: "Edit Session Timeline Render",
}


async def delivery_graph(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
) -> tuple[ProductionGraph, MaterializedGraph]:
    await session.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    graph = await session.scalar(
        select(ProductionGraph)
        .where(
            ProductionGraph.project_id == project_id,
            ProductionGraph.scope_type == "project",
            ProductionGraph.scope_entity_id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    graphs = GraphService(session)
    nodes = [{"key": key, "type": "export", "display_name": name} for key, name in _NODES.items()]
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="project",
            scope_entity_id=project_id,
            template_key="final-film-v1",
            created_by=actor_id,
            definition={"nodes": nodes, "edges": []},
        )
    if graph.current_version_id is None:
        raise ConflictError("项目生产图缺少当前版本")
    current = await graphs.get_version(graph.current_version_id)
    if current.status == "draft" and (
        graph.template_key not in {"final-film-v1", "edit-session-render-v1"}
        or current.definition not in (
            {"nodes": nodes, "edges": []},
            *({"nodes": [node], "edges": []} for node in nodes),
        )
    ):
        raise ConflictError("项目生产图有待确认的草稿，请先完成当前版本")
    materialized = await graphs.materialize_definition(version_id=current.id)
    if any(node.node_type != "export" for key, node in materialized.nodes.items() if key in _NODES):
        raise ConflictError("项目生产图中的交付节点类型不匹配")
    missing = [node for node in nodes if node["key"] not in materialized.nodes]
    if missing:
        definition = dict(current.definition)
        existing_nodes = definition.get("nodes")
        if not isinstance(existing_nodes, list):
            raise ConflictError("项目生产图缺少节点定义")
        definition["nodes"] = [*existing_nodes, *missing]
        current = await graphs.create_version(
            graph_id=graph.id,
            definition=definition,
            created_by=actor_id,
        )
        materialized = await graphs.materialize_definition(version_id=current.id)
    if current.status == "draft":
        await graphs.publish(version_id=current.id, published_by=actor_id)
    return graph, materialized
