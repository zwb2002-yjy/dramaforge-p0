"""Arq job registry — product NodeRun execution (Worker only)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.config import get_settings
from app.shared.db import get_session_factory, set_rls_context

# Ensure full MetaData / FK graph is registered in worker process (SQLAlchemy
# needs all related tables present when compiling FLUSH).
from app.access import models as _access_models  # noqa: F401
from app.assets import models as _assets_models  # noqa: F401
from app.creation import models as _creation_models  # noqa: F401
from app.delivery import models as _delivery_models  # noqa: F401
from app.events import models as _event_models  # noqa: F401
from app.execution import models as _execution_models  # noqa: F401
from app.production import models as _production_models  # noqa: F401


async def health_ping(ctx: dict[str, Any]) -> dict[str, str]:
    _ = ctx
    return {"status": "ok", "job": "health_ping"}


async def execute_node_run(ctx: dict[str, Any], node_run_id: str) -> dict[str, Any]:
    """Worker job: execute media NodeRun via product_path (Adapter OK here)."""
    from app.execution.models import NodeRun
    from app.execution.product_path import execute_media_node_run

    _ = ctx
    factory = get_session_factory()
    run_uuid = UUID(node_run_id)
    async with factory() as session:
        try:
            run = await session.get(NodeRun, run_uuid)
            if run is None:
                return {"status": "failed", "error": "node_run not found"}
            await set_rls_context(
                session,
                user_id=run.created_by,
                project_id=run.project_id,
            )
            run = await session.get(NodeRun, run_uuid)
            if run is None:
                return {"status": "failed", "error": "node_run not visible under RLS"}
            result = await execute_media_node_run(session, node_run_id=run_uuid)
            await session.commit()
            return {
                "status": "completed",
                "node_run_id": str(result.node_run_id),
                "artifact_id": str(result.artifact_id),
                "object_key": result.object_key,
                "content_hash": result.content_hash,
                "byte_size": result.byte_size,
                "face_status": result.face_status,
                "node_type": result.node_type,
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            # Best-effort: mark failed if still queued/running
            try:
                async with factory() as s2:
                    run2 = await s2.get(NodeRun, run_uuid)
                    if run2 is not None and run2.status in {"queued", "running"}:
                        run2.status = "failed"
                        run2.error_code = "WORKER_ERROR"
                        run2.error_summary = str(exc)[:500]
                        await s2.commit()
            except Exception:
                pass
            return {"status": "failed", "error": str(exc)[:300]}


async def dispatch_outbox(ctx: dict[str, Any]) -> dict[str, Any]:
    """Periodic: claim outbox + enqueue Arq jobs (no Adapter)."""
    from app.runtime.scheduler import AgentRunScheduler, RedisStreamPublisher

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        pub = RedisStreamPublisher(settings.redis_url)
        n = await AgentRunScheduler(session, publisher=pub).dispatch_pending(
            worker_id=str(ctx.get("job_id", "worker"))
        )
        return {"enqueued": n}


JOB_FUNCTIONS = [health_ping, execute_node_run, dispatch_outbox]
