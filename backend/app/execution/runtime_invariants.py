"""LOCAL-ALGO — cache/budget/cancel helpers for unit tests only.

Not S3 Production Runtime Gate. No Outbox/Arq/Provider inbox integration.

Originally: S3-style NodeRun cache / budget / cancel against shipped NodeRun rows.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, GraphNode, NodeRun
from app.shared.errors import ValidationAppError


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
    cached = await find_cached_run(
        session,
        project_id=project_id,
        graph_node_id=graph_node.id,
        input_hash=input_hash,
    )
    if cached is not None and cached.result_artifact_id is not None:
        run = NodeRun(
            project_id=project_id,
            graph_version_id=graph_version_id,
            graph_node_id=graph_node.id,
            attempt_no=cached.attempt_no + 1,
            idempotency_key=f"{graph_node.node_key}:{input_hash}:cache:{uuid4()}",
            input_hash=input_hash,
            status="cached",
            input_snapshot={},
            result_artifact_id=cached.result_artifact_id,
            reused_from_run_id=cached.id,
            provider_cost=Decimal("0"),
            platform_cost=Decimal("0"),
            created_by=created_by,
        )
        session.add(run)
        await session.flush()
        return run, budget_remaining

    if budget_remaining < cost:
        run = NodeRun(
            project_id=project_id,
            graph_version_id=graph_version_id,
            graph_node_id=graph_node.id,
            attempt_no=1,
            idempotency_key=f"{graph_node.node_key}:{input_hash}:budget:{uuid4()}",
            input_hash=input_hash,
            status="blocked_budget",
            input_snapshot={},
            provider_cost=Decimal("0"),
            created_by=created_by,
        )
        session.add(run)
        await session.flush()
        return run, budget_remaining

    art_id = None
    if produce:
        art = Artifact(
            project_id=project_id,
            artifact_type="image",
            storage_state="available",
            object_key=f"minio://local/{uuid4()}.bin",
            content_hash=input_hash,
            mime_type="application/octet-stream",
            byte_size=1,
        )
        session.add(art)
        await session.flush()
        art_id = art.id

    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node_id=graph_node.id,
        attempt_no=1,
        idempotency_key=f"{graph_node.node_key}:{input_hash}:{uuid4()}",
        input_hash=input_hash,
        status="completed",
        input_snapshot={},
        result_artifact_id=art_id,
        provider_cost=cost,
        created_by=created_by,
    )
    session.add(run)
    await session.flush()
    graph_node.latest_successful_run_id = run.id
    return run, budget_remaining - cost


def mark_stale_downstream(
    *,
    changed_node_key: str,
    node_keys: list[str],
    edges: list[tuple[str, str]],
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
