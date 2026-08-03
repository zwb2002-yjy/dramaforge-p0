"""Runtime cache/budget/cancel and database-backed dependency invariants.

Cache/budget/cancel helpers were originally unit-test-only; they remain here.
The dependency helpers are used by every Worker entry before a NodeRun claim.

Originally: S3-style NodeRun cache / budget / cancel against shipped NodeRun rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.shared.errors import ValidationAppError

_UPSTREAM_PENDING = frozenset({"queued", "running", "cancel_requested"})
_UPSTREAM_SUCCEEDED = frozenset({"completed", "cached", "completed_after_cancel"})
_UPSTREAM_FAILED = frozenset({"failed", "blocked_budget", "cancelled"})
_REVIEW_NODE_KEYS = frozenset(
    {"face_review", "video_drift_review", "continuity_review"}
)


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


async def evaluate_required_dependencies(
    session: AsyncSession,
    *,
    run: NodeRun,
) -> DependencyDecision:
    """Resolve required upstreams from GraphEdge and fail closed on bad lineage."""
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None or node.graph_version_id != run.graph_version_id:
        return DependencyDecision(
            action="fail",
            dependencies=(),
            error_code="UPSTREAM_RUN_MISSING",
            error_summary="current graph node is missing or belongs to another version",
        )

    edge_rows = list(
        (
            await session.execute(
                select(GraphEdge, GraphNode)
                .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
                .where(GraphEdge.graph_version_id == run.graph_version_id)
                .where(GraphEdge.downstream_node_id == run.graph_node_id)
                .where(GraphEdge.required.is_(True))
                .order_by(GraphEdge.input_port, GraphEdge.position, GraphNode.node_key)
            )
        )
        .tuples()
        .all()
    )
    if not edge_rows:
        return DependencyDecision(action="ready", dependencies=())

    shot_id = str((run.input_snapshot or {}).get("shot_id") or "").strip()
    upstream_node_ids = tuple(edge.upstream_node_id for edge, _ in edge_rows)
    rows = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == run.project_id)
                .where(NodeRun.graph_version_id == run.graph_version_id)
                .where(NodeRun.graph_node_id.in_(upstream_node_ids))
            )
        )
        .scalars()
        .all()
    )
    latest_by_node_id: dict[UUID, NodeRun] = {}
    for source_run in rows:
        if shot_id:
            source_shot = str(
                (source_run.input_snapshot or {}).get("shot_id") or ""
            ).strip()
            if source_shot != shot_id:
                continue
        latest_by_node_id[source_run.graph_node_id] = _latest_attempt(
            latest_by_node_id.get(source_run.graph_node_id), source_run
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
        artifact = await session.get(Artifact, source.result_artifact_id)
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
                    error_summary=(
                        f"required review {upstream_node.node_key} is {review_status}"
                    ),
                )

    if any(dependency.status in _UPSTREAM_PENDING for dependency in dependencies):
        return DependencyDecision(action="defer", dependencies=tuple(dependencies))
    return DependencyDecision(action="ready", dependencies=tuple(dependencies))


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
                    str(dependency.result_artifact_id)
                    if dependency.result_artifact_id
                    else None
                ),
            }
            for dependency in decision.dependencies
        ],
    }
    await session.flush()


async def find_cached_run(
    session: AsyncSession,
    *,
    project_id: UUID,
    graph_node_id: UUID,
    input_hash: str,
) -> NodeRun | None:
    result = await session.execute(
        select(NodeRun)
        .where(NodeRun.project_id == project_id)
        .where(NodeRun.graph_node_id == graph_node_id)
        .where(NodeRun.input_hash == input_hash)
        .where(NodeRun.status.in_(("completed", "cached")))
        .order_by(NodeRun.created_at.desc())
    )
    return result.scalars().first()


async def _next_attempt_no(session: AsyncSession, graph_node_id: UUID) -> int:
    result = await session.execute(
        select(NodeRun.attempt_no)
        .where(NodeRun.graph_node_id == graph_node_id)
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    current = result.scalar_one_or_none()
    return 1 if current is None else int(current) + 1


def _build_node_run(
    *,
    project_id: UUID,
    graph_version_id: UUID,
    graph_node: GraphNode,
    attempt_no: int,
    idempotency_key: str,
    input_hash: str,
    status: str,
    created_by: UUID,
    result_artifact_id: UUID | None = None,
    reused_from_run_id: UUID | None = None,
    provider_cost: Decimal = Decimal("0"),
    platform_cost: Decimal = Decimal("0"),
) -> NodeRun:
    """Create a NodeRun row with the common field set."""
    return NodeRun(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node_id=graph_node.id,
        attempt_no=attempt_no,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        status=status,
        input_snapshot={},
        result_artifact_id=result_artifact_id,
        reused_from_run_id=reused_from_run_id,
        provider_cost=provider_cost,
        platform_cost=platform_cost,
        created_by=created_by,
    )


async def run_or_cache(
    session: AsyncSession,
    *,
    project_id: UUID,
    graph_version_id: UUID,
    graph_node: GraphNode,
    input_hash: str,
    created_by: UUID,
    budget_remaining: Decimal,
    cost: Decimal,
    produce: bool = True,
) -> tuple[NodeRun, Decimal]:
    """Return (run, new_budget). Cached runs have zero provider cost."""
    attempt = await _next_attempt_no(session, graph_node.id)
    cached = await find_cached_run(
        session,
        project_id=project_id,
        graph_node_id=graph_node.id,
        input_hash=input_hash,
    )
    if cached is not None and cached.result_artifact_id is not None:
        run = _build_node_run(
            project_id=project_id,
            graph_version_id=graph_version_id,
            graph_node=graph_node,
            attempt_no=attempt,
            idempotency_key=f"{graph_node.node_key}:{input_hash}:cache:{uuid4()}",
            input_hash=input_hash,
            status="cached",
            created_by=created_by,
            result_artifact_id=cached.result_artifact_id,
            reused_from_run_id=cached.id,
        )
        session.add(run)
        await session.flush()
        return run, budget_remaining

    if budget_remaining < cost:
        run = _build_node_run(
            project_id=project_id,
            graph_version_id=graph_version_id,
            graph_node=graph_node,
            attempt_no=attempt,
            idempotency_key=f"{graph_node.node_key}:{input_hash}:budget:{uuid4()}",
            input_hash=input_hash,
            status="blocked_budget",
            created_by=created_by,
        )
        session.add(run)
        await session.flush()
        return run, budget_remaining

    art_id = None
    if produce:
        payload = f"node:{graph_node.node_key}:{input_hash}".encode()
        import hashlib

        ch = hashlib.sha256(payload).hexdigest()
        art = Artifact(
            project_id=project_id,
            artifact_type="image",
            storage_state="available",
            object_key=f"projects/{project_id}/nodes/{uuid4()}.bin",
            content_hash=ch if len(input_hash) != 64 else input_hash,
            mime_type="application/octet-stream",
            byte_size=len(payload),
        )
        session.add(art)
        await session.flush()
        art_id = art.id

    run = _build_node_run(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node=graph_node,
        attempt_no=attempt,
        idempotency_key=f"{graph_node.node_key}:{input_hash}:{uuid4()}",
        input_hash=input_hash,
        status="completed",
        created_by=created_by,
        result_artifact_id=art_id,
        provider_cost=cost,
    )
    session.add(run)
    await session.flush()
    graph_node.latest_successful_run_id = run.id
    return run, budget_remaining - cost


def mark_stale_downstream(
    *,
    changed_node_key: str,
    node_keys: Sequence[str],
    edges: Sequence[tuple[str, str]],
) -> list[str]:
    """Return node keys that must re-run when changed_node_key invalidates."""
    stale = {changed_node_key}
    changed = True
    while changed:
        changed = False
        for up, down in edges:
            if up in stale and down not in stale:
                stale.add(down)
                changed = True
    return [k for k in node_keys if k in stale and k != changed_node_key]


def cancel_run(run: NodeRun) -> str:
    if run.status in {"completed", "cached"}:
        return "completed_after_cancel"
    if run.status in {"queued", "running"}:
        run.status = "cancelled"
        return "cancelled"
    raise ValidationAppError(f"cannot cancel status={run.status}")


async def single_flight_claim(
    session: AsyncSession,
    *,
    project_id: UUID,
    graph_version_id: UUID,
    graph_node: GraphNode,
    input_hash: str,
    created_by: UUID,
) -> tuple[NodeRun, bool]:
    """Claim one in-flight/completed run for (project, node, input_hash).

    Returns (run, is_leader). Followers re-use the same NodeRun row; only the
    leader should create a ProviderOperation (P0 §3.1.15).
    """
    existing = (
        await session.execute(
            select(NodeRun)
            .where(NodeRun.project_id == project_id)
            .where(NodeRun.graph_node_id == graph_node.id)
            .where(NodeRun.input_hash == input_hash)
            .where(
                NodeRun.status.in_(
                    ("queued", "running", "completed", "cached", "completed_after_cancel")
                )
            )
            .order_by(NodeRun.created_at.asc())
        )
    ).scalars().first()
    if existing is not None:
        return existing, False
    attempt = await _next_attempt_no(session, graph_node.id)
    # Stable idempotency key for concurrent inserts (unique constraint)
    idem = f"sf:{graph_node.id}:{input_hash}"
    run = _build_node_run(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node=graph_node,
        attempt_no=attempt,
        idempotency_key=idem,
        input_hash=input_hash,
        status="queued",
        created_by=created_by,
    )
    session.add(run)
    try:
        await session.flush()
        return run, True
    except Exception:
        await session.rollback()
        # Race: another writer won the unique key
        again = (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .where(NodeRun.idempotency_key == idem)
            )
        ).scalar_one_or_none()
        if again is None:
            raise
        return again, False
