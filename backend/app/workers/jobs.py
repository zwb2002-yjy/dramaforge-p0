"""Arq job registry — product NodeRun execution."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.config import get_settings
from app.shared.db import get_session_factory, set_rls_context


async def health_ping(ctx: dict[str, Any]) -> dict[str, str]:
    """No-op job used to prove worker process can execute tasks."""
    _ = ctx
    return {"status": "ok", "job": "health_ping"}


async def execute_node_run(ctx: dict[str, Any], node_run_id: str) -> dict[str, Any]:
    """Worker job: load NodeRun from PG, execute keyframe product path."""
    from app.execution.models import NodeRun
    from app.execution.product_path import execute_keyframe_node_run

    _ = ctx
    factory = get_session_factory()
    run_uuid = UUID(node_run_id)
    async with factory() as session:
        # Bootstrap without project context to resolve run, then re-set RLS
        run = await session.get(NodeRun, run_uuid)
        if run is None:
            return {"status": "failed", "error": "node_run not found"}
        await set_rls_context(
            session,
            user_id=run.created_by,
            project_id=run.project_id,
        )
        # Re-load under RLS
        run = await session.get(NodeRun, run_uuid)
        if run is None:
            return {"status": "failed", "error": "node_run not visible under RLS"}
        try:
            result = await execute_keyframe_node_run(session, node_run_id=run_uuid)
            await session.commit()
            return {
                "status": "completed",
                "node_run_id": str(result.node_run_id),
                "artifact_id": str(result.artifact_id),
                "object_key": result.object_key,
                "content_hash": result.content_hash,
                "byte_size": result.byte_size,
                "face_status": result.face_status,
            }
        except Exception as exc:  # noqa: BLE001
            await session.commit()
            return {"status": "failed", "error": str(exc)[:300]}


async def dispatch_outbox(ctx: dict[str, Any]) -> dict[str, Any]:
    """Periodic: claim outbox + drain queued node runs."""
    from app.runtime.scheduler import AgentRunScheduler, RedisStreamPublisher

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        pub = RedisStreamPublisher(settings.redis_url)
        n = await AgentRunScheduler(session, publisher=pub).dispatch_pending(
            worker_id=str(ctx.get("job_id", "worker"))
        )
        return {"dispatched": n}


JOB_FUNCTIONS = [health_ping, execute_node_run, dispatch_outbox]
