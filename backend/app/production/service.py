"""Graph validation, relational materialization, and publish boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import GraphEdge, GraphNode
from app.production.models import (
    GraphVersion,
    ProductionGraph,
    assert_graph_version_mutable,
    definition_hash,
)
from app.shared.enums import GraphStatus
from app.shared.errors import NotFoundError, ValidationAppError


@dataclass(frozen=True, slots=True)
class MaterializedGraph:
    version: GraphVersion
    nodes: dict[str, GraphNode]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True, slots=True)
class _NodeSpec:
    key: str
    node_type: str
    display_name: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    config: dict[str, object]
    cacheable: bool


@dataclass(frozen=True, slots=True)
class _EdgeSpec:
    upstream_key: str
    downstream_key: str
    output_port: str
    input_port: str
    position: int
    required: bool


def _validation_error(message: str, *, code: str = "GRAPH_DEFINITION_INVALID") -> None:
    raise ValidationAppError(message, details={"code": code})


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        _validation_error(f"{field} must be an object")
    value_map = cast(dict[object, object], value)
    return {str(key): item for key, item in value_map.items()}


def _node_specs(definition: dict[str, object]) -> tuple[_NodeSpec, ...]:
    raw_nodes = definition.get("nodes")
    if not isinstance(raw_nodes, list):
        _validation_error("graph nodes must be an array")
    node_items = cast(list[object], raw_nodes)
    specs: list[_NodeSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(node_items):
        if isinstance(raw, str):
            key = raw.strip()
            node_type = key
            display_name = key.replace("_", " ").title()
            input_schema: dict[str, object] = {}
            output_schema: dict[str, object] = {}
            config: dict[str, object] = {}
            cacheable = True
        elif isinstance(raw, dict):
            key = str(raw.get("key") or "").strip()
            node_type = str(raw.get("type") or raw.get("node_type") or "").strip()
            display_name = str(raw.get("display_name") or key).strip()
            input_schema = _mapping(raw.get("input_schema"), field="node.input_schema")
            output_schema = _mapping(raw.get("output_schema"), field="node.output_schema")
            config = _mapping(raw.get("config"), field="node.config")
            cacheable = raw.get("cacheable", True) is not False
        else:
            _validation_error(f"graph node at index {index} must be a string or object")
        if not key or not node_type:
            _validation_error(f"graph node at index {index} requires key and type")
        if key in seen:
            _validation_error(f"duplicate graph node key: {key}")
        seen.add(key)
        specs.append(
            _NodeSpec(
                key=key,
                node_type=node_type,
                display_name=display_name or key,
                input_schema=input_schema,
                output_schema=output_schema,
                config=config,
                cacheable=cacheable,
            )
        )
    return tuple(specs)


def _edge_specs(
    definition: dict[str, object], *, node_keys: set[str]
) -> tuple[_EdgeSpec, ...]:
    raw_edges = definition.get("edges")
    if not isinstance(raw_edges, list):
        _validation_error("graph edges must be an array")
    edge_items = cast(list[object], raw_edges)
    specs: list[_EdgeSpec] = []
    seen: set[tuple[str, str, str, str, int]] = set()
    required_inputs: set[tuple[str, str, int]] = set()
    for index, raw in enumerate(edge_items):
        if isinstance(raw, list | tuple) and len(raw) == 2:
            upstream = str(raw[0]).strip()
            downstream = str(raw[1]).strip()
            output_port = upstream
            input_port = upstream
            position = 0
            required = True
        elif isinstance(raw, dict):
            upstream = str(
                raw.get("upstream") or raw.get("from") or raw.get("upstream_key") or ""
            ).strip()
            downstream = str(
                raw.get("downstream") or raw.get("to") or raw.get("downstream_key") or ""
            ).strip()
            output_port = str(raw.get("output_port") or upstream).strip()
            input_port = str(raw.get("input_port") or upstream).strip()
            try:
                position = int(raw.get("position", 0))
            except (TypeError, ValueError):
                _validation_error(f"graph edge at index {index} has invalid position")
            required = raw.get("required", True) is not False
        else:
            _validation_error(f"graph edge at index {index} must contain two endpoints")
        if upstream not in node_keys or downstream not in node_keys:
            _validation_error(
                f"graph edge at index {index} references a missing endpoint"
            )
        if upstream == downstream:
            _validation_error(f"graph edge at index {index} cannot be a self-loop")
        if not output_port or not input_port or position < 0:
            _validation_error(f"graph edge at index {index} has invalid ports or position")
        identity = (upstream, output_port, downstream, input_port, position)
        if identity in seen:
            _validation_error(f"duplicate graph edge at index {index}")
        seen.add(identity)
        required_input = (downstream, input_port, position)
        if required and required_input in required_inputs:
            _validation_error(
                f"duplicate required input port: {downstream}.{input_port}[{position}]"
            )
        if required:
            required_inputs.add(required_input)
        specs.append(
            _EdgeSpec(
                upstream_key=upstream,
                downstream_key=downstream,
                output_port=output_port,
                input_port=input_port,
                position=position,
                required=required,
            )
        )

    adjacency: dict[str, list[str]] = {key: [] for key in node_keys}
    indegree = {key: 0 for key in node_keys}
    for edge in specs:
        adjacency[edge.upstream_key].append(edge.downstream_key)
        indegree[edge.downstream_key] += 1
    ready = [key for key, count in indegree.items() if count == 0]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for downstream in adjacency[key]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)
    if visited != len(node_keys):
        _validation_error("graph definition contains a cycle")
    return tuple(specs)


def validate_graph_definition(
    definition: dict[str, object],
) -> tuple[tuple[_NodeSpec, ...], tuple[_EdgeSpec, ...]]:
    """Validate a graph definition before any relational rows are written."""
    if not isinstance(definition, dict):
        _validation_error("graph definition must be an object")
    nodes = _node_specs(definition)
    edges = _edge_specs(definition, node_keys={node.key for node in nodes})
    return nodes, edges


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
        if scope_type not in {"shot", "episode", "shot_experiment", "project"}:
            raise ValidationAppError(
                "scope_type must be shot, episode, shot_experiment or project"
            )
        body = definition or {"nodes": [], "edges": []}
        validate_graph_definition(body)
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

    async def materialize_definition(self, *, version_id: UUID) -> MaterializedGraph:
        """Idempotently materialize one draft definition into GraphNode/GraphEdge.

        Published versions are accepted only when their relational structure already
        matches the frozen JSON definition. This prevents silent repair of production
        history whose source definition cannot be proven.
        """
        version = await self.get_version(version_id)
        nodes_spec, edges_spec = validate_graph_definition(dict(version.definition or {}))
        existing_nodes = list(
            (
                await self._session.execute(
                    select(GraphNode).where(GraphNode.graph_version_id == version.id)
                )
            )
            .scalars()
            .all()
        )
        existing_by_key = {node.node_key: node for node in existing_nodes}
        expected_keys = {spec.key for spec in nodes_spec}
        unexpected = set(existing_by_key) - expected_keys
        if unexpected:
            _validation_error(
                f"graph relation has nodes absent from definition: {sorted(unexpected)}",
                code="GRAPH_RELATION_MISMATCH",
            )
        if version.status != GraphStatus.DRAFT.value:
            missing = expected_keys - set(existing_by_key)
            if missing:
                _validation_error(
                    f"published graph relation is missing nodes: {sorted(missing)}",
                    code="GRAPH_RELATION_MISMATCH",
                )

        for spec in nodes_spec:
            node = existing_by_key.get(spec.key)
            if node is None:
                node = GraphNode(
                    graph_version_id=version.id,
                    node_key=spec.key,
                    node_type=spec.node_type,
                    display_name=spec.display_name,
                    input_schema=spec.input_schema,
                    output_schema=spec.output_schema,
                    config=spec.config,
                    cacheable=spec.cacheable,
                )
                self._session.add(node)
                existing_by_key[spec.key] = node
            elif (
                node.node_type != spec.node_type
                or node.display_name != spec.display_name
                or dict(node.input_schema or {}) != spec.input_schema
                or dict(node.output_schema or {}) != spec.output_schema
                or dict(node.config or {}) != spec.config
                or node.cacheable != spec.cacheable
            ):
                if version.status != GraphStatus.DRAFT.value:
                    _validation_error(
                        f"published graph node differs from definition: {spec.key}",
                        code="GRAPH_RELATION_MISMATCH",
                    )
                node.node_type = spec.node_type
                node.display_name = spec.display_name
                node.input_schema = spec.input_schema
                node.output_schema = spec.output_schema
                node.config = spec.config
                node.cacheable = spec.cacheable
        await self._session.flush()

        existing_edges = list(
            (
                await self._session.execute(
                    select(GraphEdge).where(GraphEdge.graph_version_id == version.id)
                )
            )
            .scalars()
            .all()
        )
        node_key_by_id = {node.id: node.node_key for node in existing_by_key.values()}

        def edge_identity(edge: GraphEdge) -> tuple[str, str, str, str, int, bool]:
            return (
                node_key_by_id.get(edge.upstream_node_id, ""),
                edge.output_port,
                node_key_by_id.get(edge.downstream_node_id, ""),
                edge.input_port,
                edge.position,
                edge.required,
            )

        expected_edge_ids = {
            (
                spec.upstream_key,
                spec.output_port,
                spec.downstream_key,
                spec.input_port,
                spec.position,
                spec.required,
            )
            for spec in edges_spec
        }
        actual_edge_ids = {edge_identity(edge) for edge in existing_edges}
        if version.status != GraphStatus.DRAFT.value and actual_edge_ids != expected_edge_ids:
            _validation_error(
                "published graph edges differ from definition",
                code="GRAPH_RELATION_MISMATCH",
            )
        if version.status == GraphStatus.DRAFT.value and actual_edge_ids != expected_edge_ids:
            await self._session.execute(
                delete(GraphEdge).where(GraphEdge.graph_version_id == version.id)
            )
            existing_edges = []
            for edge_spec in edges_spec:
                edge = GraphEdge(
                    graph_version_id=version.id,
                    upstream_node_id=existing_by_key[edge_spec.upstream_key].id,
                    output_port=edge_spec.output_port,
                    downstream_node_id=existing_by_key[edge_spec.downstream_key].id,
                    input_port=edge_spec.input_port,
                    position=edge_spec.position,
                    required=edge_spec.required,
                )
                self._session.add(edge)
                existing_edges.append(edge)
            await self._session.flush()

        return MaterializedGraph(
            version=version,
            nodes=dict(existing_by_key),
            edges=tuple(existing_edges),
        )

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
        validate_graph_definition(definition)
        version.definition = definition
        version.definition_hash = definition_hash(definition)
        await self.materialize_definition(version_id=version.id)
        await self._session.flush()
        await self._session.refresh(version)
        return version

    async def publish(self, *, version_id: UUID, published_by: UUID) -> GraphVersion:
        version = await self.get_version(version_id)
        if version.status != GraphStatus.DRAFT.value:
            raise ValidationAppError("only draft versions can be published")
        materialized = await self.materialize_definition(version_id=version.id)
        if definition_hash(dict(version.definition or {})) != version.definition_hash:
            _validation_error(
                "graph definition hash does not match definition",
                code="GRAPH_DEFINITION_HASH_MISMATCH",
            )
        if len(materialized.nodes) != len(_node_specs(dict(version.definition or {}))):
            _validation_error("graph node materialization is incomplete")
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
