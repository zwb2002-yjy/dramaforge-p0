"""Per-shot review, lock, local re-run, and audited manual media (P0)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.execution.models import Artifact, GraphNode, NodeRun, ShotHumanLock
from app.execution.runtime_invariants import mark_stale_downstream
from app.execution.shot_p0 import SHOT_EDGES, SHOT_NODES, is_shot_locked, set_shot_lock
from app.shared.errors import NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


@dataclass(frozen=True)
class ShotReviewResult:
    shot_id: UUID
    status: str
    locked: bool
    message: str


async def get_shot_or_404(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID
) -> Shot:
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise NotFoundError("shot not found")
    return shot


async def approve_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    note: str = "",
) -> ShotReviewResult:
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked; unlock before approve")
    shot.status = "review_passed"
    shot.version = int(getattr(shot, "version", 1) or 1) + 1
    await session.flush()
    return ShotReviewResult(
        shot_id=shot_id,
        status=shot.status,
        locked=False,
        message=note or "approved",
    )


async def reject_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    reason: str,
) -> ShotReviewResult:
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked; unlock before reject")
    if not reason.strip():
        raise ValidationAppError("reject reason required")
    shot.status = "review_rejected"
    await session.flush()
    return ShotReviewResult(
        shot_id=shot_id,
        status=shot.status,
        locked=False,
        message=reason[:500],
    )


async def lock_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    locked: bool,
) -> ShotReviewResult:
    await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    row = await set_shot_lock(
        session, project_id=project_id, shot_id=shot_id, user_id=user_id, locked=locked
    )
    return ShotReviewResult(
        shot_id=shot_id,
        status="locked" if locked else "unlocked",
        locked=row.locked,
        message="human lock set" if locked else "human lock cleared",
    )


async def start_shot_nodes(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    node_keys: list[str] | None = None,
) -> list[UUID]:
    """Create queued NodeRuns for requested shot-p0-v1 nodes (enqueue-only)."""
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    keys = node_keys or list(SHOT_NODES)
    for k in keys:
        if k not in SHOT_NODES:
            raise ValidationAppError(f"unknown node key: {k}")

    from app.execution.shot_p0 import _NODE_TYPE
    from app.production.models import ProductionGraph
    from app.production.service import GraphService

    graphs = GraphService(session)
    existing = (
        await session.execute(
            select(ProductionGraph).where(
                ProductionGraph.project_id == project_id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        graph = existing
        if graph.current_version_id is None:
            graph = await graphs.create_graph(
                project_id=project_id,
                scope_type="shot",
                scope_entity_id=shot_id,
                template_key="shot-p0-v1",
                created_by=user_id,
                definition={"nodes": list(SHOT_NODES), "edges": SHOT_EDGES},
            )
    else:
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="shot",
            scope_entity_id=shot_id,
            template_key="shot-p0-v1",
            created_by=user_id,
            definition={"nodes": list(SHOT_NODES), "edges": SHOT_EDGES},
        )
    assert graph.current_version_id is not None
    version_id = graph.current_version_id
    run_ids: list[UUID] = []
    for key in keys:
        # Reuse graph node if already present for this version
        node = (
            await session.execute(
                select(GraphNode).where(
                    GraphNode.graph_version_id == version_id,
                    GraphNode.node_key == key,
                )
            )
        ).scalar_one_or_none()
        if node is None:
            node = GraphNode(
                graph_version_id=version_id,
                node_key=key,
                node_type=_NODE_TYPE.get(key, key),
                display_name=key,
                cacheable=True,
            )
            session.add(node)
            await session.flush()
        ih = hashlib.sha256(f"{shot_id}:{key}:{uuid4()}".encode()).hexdigest()
        # attempt_no: count prior runs for this node
        prior = (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == project_id,
                    NodeRun.graph_node_id == node.id,
                )
            )
        ).scalars().all()
        attempt = len(list(prior)) + 1
        run = NodeRun(
            project_id=project_id,
            graph_version_id=version_id,
            graph_node_id=node.id,
            attempt_no=attempt,
            idempotency_key=f"start:{key}:{shot_id}:{ih}",
            input_hash=ih,
            status="queued",
            input_snapshot={"shot_id": str(shot_id), "node_key": key, "prompt": f"{key}:{shot_id}"},
            created_by=user_id,
        )
        session.add(run)
        await session.flush()
        run_ids.append(run.id)
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    # Keep shot.status within product vocabulary used by UI/import (avoid unknown enums)
    if shot.status in {"draft", "pending", "review_rejected", "review_passed"}:
        shot.status = "in_production"
    await session.flush()
    return run_ids


async def local_rerun_from_node(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    changed_node_key: str,
) -> list[str]:
    """Mark correct downstream stale and return keys that must re-run."""
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    if changed_node_key not in SHOT_NODES:
        raise ValidationAppError(f"unknown node: {changed_node_key}")
    stale = mark_stale_downstream(
        changed_node_key=changed_node_key,
        node_keys=list(SHOT_NODES),
        edges=SHOT_EDGES,
    )
    # Include the changed node itself
    to_run = [changed_node_key] + [k for k in stale if k != changed_node_key]
    await start_shot_nodes(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user_id,
        node_keys=to_run,
    )
    return to_run


async def upload_manual_media(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    node_key: str,
    data: bytes,
    mime_type: str,
    note: str = "",
    store: ObjectStore | None = None,
) -> Artifact:
    """Audited manual media as immutable Artifact for a shot node (zero Provider cost)."""
    if not data:
        raise ValidationAppError("empty media bytes")
    if node_key not in SHOT_NODES:
        raise ValidationAppError(f"unknown node: {node_key}")
    obj = store or get_object_store()
    content_hash = hashlib.sha256(data).hexdigest()
    object_key = f"projects/{project_id}/manual/{shot_id}/{node_key}/{content_hash[:16]}"
    stored = await obj.put_bytes(object_key=object_key, data=data, mime_type=mime_type)
    # Encode audit trail in object_key path (Artifact has no free-form metadata column).
    # object_key already contains project/shot/node/hash.
    _ = note
    _ = user_id
    # Map to frozen artifact_type enum (image/video/audio/document/…)
    if mime_type.startswith("video/"):
        art_type = "video"
    elif mime_type.startswith("audio/"):
        art_type = "audio"
    elif mime_type.startswith("image/") or mime_type == "application/octet-stream":
        art_type = "image"
    else:
        art_type = "document"
    art = Artifact(
        project_id=project_id,
        artifact_type=art_type,
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        byte_size=stored.byte_size,
        mime_type=mime_type,
        storage_state="available",
        produced_by_run_id=None,
        delete_reason=f"audited_manual_upload shot={shot_id} node={node_key}"[:240],
    )
    session.add(art)
    await session.flush()
    return art


async def shot_status_summary(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID
) -> dict[str, object]:
    await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    locked = await is_shot_locked(session, project_id=project_id, shot_id=shot_id)
    runs = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    shot_runs = [
        r
        for r in runs
        if (r.input_snapshot or {}).get("shot_id") == str(shot_id)
        or str(shot_id) in str(r.idempotency_key)
    ]
    failed = [r for r in shot_runs if r.status == "failed"]
    guidance = None
    if failed:
        fr = failed[0]
        code = fr.error_code or "UNKNOWN"
        guidance = {
            "error_code": code,
            "summary": fr.error_summary,
            "retry_suggestion": _retry_suggestion(code),
        }
    shot = await session.get(Shot, shot_id)
    return {
        "shot_id": str(shot_id),
        "status": shot.status if shot else "unknown",
        "locked": locked,
        "node_run_count": len(shot_runs),
        "failed_count": len(failed),
        "guidance": guidance,
        "pipeline": list(SHOT_NODES),
    }


def _retry_suggestion(code: str) -> str:
    mapping = {
        "PROVIDER_NOT_CONFIGURED": "配置 BYOK Provider 或使用受审计手工媒体上传",
        "CANONICAL_REFERENCE_REQUIRED": "先注册主角 canonical Reference",
        "PROVIDER_FAILED": "检查 Provider 状态后重试该节点及正确下游",
        "QUEUE_UNAVAILABLE": "启动 Redis 与 Arq Worker 后 dispatch/enqueue",
    }
    return mapping.get(code, "查看 NodeRun error_summary 后局部重跑失败节点")
