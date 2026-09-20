"""Runtime dependency invariants for the canonical Worker path.

The Worker and production snapshot share these fail-closed dependency checks.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun

_UPSTREAM_PENDING = frozenset({"queued", "running", "cancel_requested"})
_UPSTREAM_SUCCEEDED = frozenset({"completed", "cached", "completed_after_cancel"})
_UPSTREAM_FAILED = frozenset({"failed", "cancelled"})
_REVIEW_NODE_KEYS = frozenset({"identity_review", "video_drift_review", "continuity_review"})


@dataclass(frozen=True, slots=True)
class UpstreamDependency:
    node_key: str
    run_id: UUID | None
    status: str
    result_artifact_id: UUID | None


@dataclass(frozen=True, slots=True)
class DependencyDecision:
    action: Literal["ready", "defer", "fail"]
    dependencies: tuple[UpstreamDependency, ...]
    error_code: str | None = None
    error_summary: str | None = None


def _latest_attempt(current: NodeRun | None, candidate: NodeRun) -> NodeRun:
    if current is None:
        return candidate
    current_key = (current.attempt_no, current.created_at, str(current.id))
    candidate_key = (candidate.attempt_no, candidate.created_at, str(candidate.id))
    return candidate if candidate_key > current_key else current


def _evaluate_loaded_dependencies(
    *,
    run: NodeRun,
    node: GraphNode | None,
    edge_rows: list[tuple[GraphEdge, GraphNode]],
    latest_by_node_id: dict[UUID, NodeRun],
    artifacts: dict[UUID, Artifact],
) -> DependencyDecision:
    """One decision implementation for Worker checks and batched read models."""
    if node is None or node.graph_version_id != run.graph_version_id:
        return DependencyDecision(
            action="fail",
            dependencies=(),
            error_code="UPSTREAM_RUN_MISSING",
            error_summary="current graph node is missing or belongs to another version",
        )
    dependencies: list[UpstreamDependency] = []
    for edge, upstream_node in edge_rows:
        source = latest_by_node_id.get(edge.upstream_node_id)
        dependencies.append(
            UpstreamDependency(
                node_key=upstream_node.node_key,
                run_id=source.id if source else None,
                status=source.status if source else "missing",
                result_artifact_id=source.result_artifact_id if source else None,
            )
        )
        if source is None:
            return DependencyDecision(
                action="fail",
                dependencies=tuple(dependencies),
                error_code="UPSTREAM_RUN_MISSING",
                error_summary=f"required upstream run is missing: {upstream_node.node_key}",
            )
        if source.status in _UPSTREAM_PENDING:
            continue
        if source.status in _UPSTREAM_FAILED or source.status not in _UPSTREAM_SUCCEEDED:
            return DependencyDecision(
                action="fail",
                dependencies=tuple(dependencies),
                error_code="UPSTREAM_TERMINAL_FAILURE",
                error_summary=(
                    f"required upstream {upstream_node.node_key} ended with {source.status}"
                ),
            )
        if source.status == "completed_after_cancel" and not bool(
            (source.output_summary or {}).get("adopted_after_cancel")
        ):
            return DependencyDecision(
                action="fail",
                dependencies=tuple(dependencies),
                error_code="UPSTREAM_TERMINAL_FAILURE",
                error_summary=(
                    f"required upstream {upstream_node.node_key} completed after cancel "
                    "without explicit adoption"
                ),
            )
        if source.result_artifact_id is None:
            return DependencyDecision(
                action="fail",
                dependencies=tuple(dependencies),
                error_code="UPSTREAM_ARTIFACT_MISSING",
                error_summary=(
                    f"required upstream {upstream_node.node_key} has no result Artifact"
                ),
            )
        artifact = artifacts.get(source.result_artifact_id)
        if (
            artifact is None
            or artifact.project_id != run.project_id
            or artifact.storage_state != "available"
            or artifact.deleted_at is not None
        ):
            return DependencyDecision(
                action="fail",
                dependencies=tuple(dependencies),
                error_code="UPSTREAM_ARTIFACT_MISSING",
                error_summary=(
                    f"required upstream {upstream_node.node_key} Artifact is unavailable"
                ),
            )
        if upstream_node.node_key in _REVIEW_NODE_KEYS:
            review_status = str((source.output_summary or {}).get("status") or "")
            if review_status in {"blocked", "needs_human", "failed"}:
                return DependencyDecision(
                    action="fail",
                    dependencies=tuple(dependencies),
                    error_code="UPSTREAM_TERMINAL_FAILURE",
                    error_summary=(f"required review {upstream_node.node_key} is {review_status}"),
                )

    if any(dependency.status in _UPSTREAM_PENDING for dependency in dependencies):
        return DependencyDecision(action="defer", dependencies=tuple(dependencies))
    return DependencyDecision(action="ready", dependencies=tuple(dependencies))


async def evaluate_required_dependencies_many(
    session: AsyncSession,
    *,
    runs: list[NodeRun],
) -> dict[UUID, DependencyDecision]:
    """Read dependency facts in four queries, never once per run or upstream.

    Grouping preserves the Worker contract: exact project/graph/shot scope,
    latest attempt, required-edge ordering, and fail-closed Artifact/review checks.
    No result is cached across transactions or used to mutate production facts.
    """
    if not runs:
        return {}
    node_ids = {run.graph_node_id for run in runs}
    version_ids = {run.graph_version_id for run in runs}
    project_ids = {run.project_id for run in runs}
    nodes = {
        node.id: node
        for node in (await session.scalars(select(GraphNode).where(GraphNode.id.in_(node_ids))))
    }
    edges: dict[tuple[UUID, UUID], list[tuple[GraphEdge, GraphNode]]] = {}
    edge_rows = (
        await session.execute(
            select(GraphEdge, GraphNode)
            .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
            .where(
                GraphEdge.graph_version_id.in_(version_ids),
                GraphEdge.downstream_node_id.in_(node_ids),
                GraphEdge.required.is_(True),
            )
            .order_by(GraphEdge.input_port, GraphEdge.position, GraphNode.node_key)
        )
    ).all()
    for edge, upstream_node in edge_rows:
        edges.setdefault((edge.graph_version_id, edge.downstream_node_id), []).append(
            (edge, upstream_node)
        )
    upstream_ids = {edge.upstream_node_id for edge, _ in edge_rows}
    latest: dict[tuple[UUID, UUID, str, UUID], NodeRun] = {}
    if upstream_ids:
        sources = await session.scalars(
            select(NodeRun).where(
                NodeRun.project_id.in_(project_ids),
                NodeRun.graph_version_id.in_(version_ids),
                NodeRun.graph_node_id.in_(upstream_ids),
            )
        )
        for source in sources:
            shot_id = str((source.input_snapshot or {}).get("shot_id") or "").strip()
            # An unscoped run historically resolves across shots. Scoped runs
            # must never inherit that fallback when their own upstream is absent.
            for scope in {"", shot_id}:
                key = (source.project_id, source.graph_version_id, scope, source.graph_node_id)
                latest[key] = _latest_attempt(latest.get(key), source)
    artifact_ids = {source.result_artifact_id for source in latest.values()} - {None}
    artifacts = {
        artifact.id: artifact
        for artifact in (
            await session.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids)))
            if artifact_ids
            else []
        )
    }
    decisions: dict[UUID, DependencyDecision] = {}
    for run in runs:
        shot_id = str((run.input_snapshot or {}).get("shot_id") or "").strip()
        required = edges.get((run.graph_version_id, run.graph_node_id), [])
        scoped_sources = {}
        for edge, _ in required:
            scoped_source = latest.get(
                (run.project_id, run.graph_version_id, shot_id, edge.upstream_node_id)
            )
            if scoped_source is not None:
                scoped_sources[edge.upstream_node_id] = scoped_source
        decisions[run.id] = _evaluate_loaded_dependencies(
            run=run,
            node=nodes.get(run.graph_node_id),
            edge_rows=required,
            latest_by_node_id=scoped_sources,
            artifacts=artifacts,
        )
    return decisions


async def evaluate_required_dependencies(
    session: AsyncSession,
    *,
    run: NodeRun,
) -> DependencyDecision:
    """Resolve required upstreams from GraphEdge and fail closed on bad lineage."""
    return (await evaluate_required_dependencies_many(session, runs=[run]))[run.id]


async def fail_run_for_dependency(
    session: AsyncSession,
    *,
    run: NodeRun,
    decision: DependencyDecision,
) -> None:
    """Persist a dependency failure without claiming or calling a Provider."""
    if decision.action != "fail" or not decision.error_code:
        raise ValueError("dependency decision is not a failure")
    from datetime import UTC, datetime

    run.status = "failed"
    run.error_code = decision.error_code
    run.error_summary = (decision.error_summary or decision.error_code)[:500]
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "status": "failed",
        "error_code": decision.error_code,
        "upstream_dependencies": [
            {
                "node_key": dependency.node_key,
                "run_id": str(dependency.run_id) if dependency.run_id else None,
                "status": dependency.status,
                "result_artifact_id": (
                    str(dependency.result_artifact_id) if dependency.result_artifact_id else None
                ),
            }
            for dependency in decision.dependencies
        ],
    }
    await session.flush()
