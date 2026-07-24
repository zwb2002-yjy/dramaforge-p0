"""Arq job registry — product NodeRun execution (Worker only)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.shared.db import get_session_factory, set_rls_context
from app.shared.errors import AppError, NodeRunAlreadyClaimedError
from app.shared.model_registry import load_all_models

# Ensure full MetaData / FK graph is registered in worker process (SQLAlchemy
# needs all related tables present when compiling FLUSH).
load_all_models()
logger = logging.getLogger(__name__)


def _worker_failure_code(exc: Exception) -> str:
    message = str(exc).strip()
    prefix = message.partition(":")[0].strip()
    if prefix in {
        "CANONICAL_REFERENCE_REQUIRED",
        "PROVIDER_FAILED",
        "PROVIDER_NOT_CONFIGURED",
    }:
        return prefix
    if isinstance(exc, AppError) and exc.code != "VALIDATION_ERROR":
        return exc.code
    return "WORKER_ERROR"


async def health_ping(ctx: dict[str, Any]) -> dict[str, str]:
    _ = ctx
    return {"status": "ok", "job": "health_ping"}


async def execute_node_run(ctx: dict[str, Any], node_run_id: str) -> dict[str, Any]:
    """Worker job: execute media NodeRun via product_path (Adapter OK here)."""
    from app.execution.models import NodeRun
    from app.execution.product_path import claim_media_node_run, execute_media_node_run

    _ = ctx
    factory = get_session_factory()
    run_uuid = UUID(node_run_id)
    worker_user_id = None
    worker_project_id = None
    async with factory() as session:
        try:
            run = await session.get(NodeRun, run_uuid)
            if run is None:
                return {"status": "failed", "error": "node_run not found"}
            worker_user_id = run.created_by
            worker_project_id = run.project_id
            await set_rls_context(
                session,
                user_id=worker_user_id,
                project_id=worker_project_id,
            )
            run = await session.get(NodeRun, run_uuid)
            if run is None:
                return {"status": "failed", "error": "node_run not visible under RLS"}
            await claim_media_node_run(session, node_run_id=run_uuid)
            result = await execute_media_node_run(
                session,
                node_run_id=run_uuid,
                already_claimed=True,
            )
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
        except NodeRunAlreadyClaimedError:
            await session.rollback()
            return {"status": "already_claimed", "node_run_id": node_run_id}
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            # Fail-stop after a claimed Provider attempt. Failed runs are not
            # automatically requeued, so an ambiguous remote outcome cannot
            # trigger a duplicate submission.
            try:
                async with factory() as s2:
                    await set_rls_context(
                        s2,
                        user_id=worker_user_id,
                        project_id=worker_project_id,
                    )
                    run2 = await s2.get(NodeRun, run_uuid)
                    if run2 is not None and run2.status in {"queued", "running"}:
                        run2.status = "failed"
                        run2.error_code = _worker_failure_code(exc)
                        run2.error_summary = str(exc)[:500]
                        from datetime import UTC, datetime

                        run2.finished_at = datetime.now(UTC)
                        run2.output_summary = {
                            "status": "failed",
                            "error_code": run2.error_code,
                            "worker_boundary": True,
                        }
                        await s2.commit()
            except Exception:
                logger.exception(
                    "Unable to persist failed NodeRun %s after worker exception",
                    node_run_id,
                )
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
