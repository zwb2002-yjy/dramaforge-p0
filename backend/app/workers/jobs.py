"""Arq job registry — product NodeRun execution (Worker only)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from arq import Retry

from app.config import get_settings
from app.shared.db import get_session_factory, set_node_run_rls_context
from app.shared.errors import (
    AppError,
    NodeRunAlreadyClaimedError,
    ProviderRateLimitedError,
    ProviderTaskCancelledError,
    ProviderTaskPendingError,
)
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
        "PROVIDER_CREATE_FAILED",
        "PROVIDER_FAILED",
        "PROVIDER_MEDIA_INVALID",
        "PROVIDER_MEDIA_DOWNLOAD_FAILED",
        "PROVIDER_MEDIA_URL_INVALID",
        "PROVIDER_MEDIA_MISSING",
        "PROVIDER_NOT_CONFIGURED",
        "PROVIDER_RESPONSE_INVALID",
        "PROVIDER_SUBMISSION_UNKNOWN",
        "UPSTREAM_ARTIFACT_MISSING",
        "UPSTREAM_RUN_MISSING",
        "UPSTREAM_TERMINAL_FAILURE",
    }:
        return prefix
    if isinstance(exc, AppError) and exc.code != "VALIDATION_ERROR":
        return exc.code
    return "WORKER_ERROR"


async def health_ping(ctx: dict[str, Any]) -> dict[str, str]:
    _ = ctx
    return {"status": "ok", "job": "health_ping"}


async def recover_interrupted_provider_jobs(ctx: dict[str, Any]) -> None:
    """Resume polling persisted remote tasks after a Heavy Worker restart."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.execution.models import NodeRun, ProviderOperation
    from app.runtime.scheduler import NodeRunScheduler
    from app.shared.db import (
        list_resumable_provider_node_run_rls_scopes,
        set_rls_context,
    )

    _ = ctx
    factory = get_session_factory()
    async with factory() as session:
        # Persisted remote identity is authoritative across candidate upgrades.
        candidates = await list_resumable_provider_node_run_rls_scopes(
            session,
            limit=50,
            source_commit=None,
        )
        for node_run_id, scope in candidates:
            await set_rls_context(
                session,
                user_id=scope.user_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
            )
            run = await session.scalar(
                select(NodeRun).where(NodeRun.id == node_run_id).with_for_update()
            )
            operation = await session.scalar(
                select(ProviderOperation)
                .where(
                    ProviderOperation.node_run_id == node_run_id,
                    ProviderOperation.execution_path_version == "unified-v1",
                )
                .order_by(ProviderOperation.attempt_no.desc())
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                run is None
                or run.status not in {"running", "cancel_requested"}
                or operation is None
            ):
                await session.rollback()
                continue
            if operation.provider_operation_id is None:
                started = operation.created_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                if operation.status == "submission_started" and started < datetime.now(
                    UTC
                ) - timedelta(minutes=30):
                    operation.status = "unknown_submission"
                    operation.error_code = "PROVIDER_SUBMISSION_UNKNOWN"
                    operation.error_summary = (
                        "Interrupted submission has no remote identity; do not resubmit."
                    )
                    run.status = "failed"
                    run.error_code = operation.error_code
                    run.error_summary = operation.error_summary
                    run.finished_at = operation.completed_at = datetime.now(UTC)
                    await session.commit()
                else:
                    await session.rollback()
                continue
            if operation.status not in {"submitted", "running", "timed_out", "cancel_requested"}:
                await session.rollback()
                continue
            snapshot = dict(run.input_snapshot or {})
            raw_resume_count = snapshot.get("provider_poll_resume_count")
            resume_count = (raw_resume_count if isinstance(raw_resume_count, int) else 0) + 1
            snapshot["provider_poll_resume_count"] = resume_count
            snapshot["dispatch_generation"] = (
                f"provider-resume-{str(operation.id)[:12]}-{resume_count}"
            )
            run.input_snapshot = snapshot
            # The queued status makes the existing claim path reusable, while
            # cancellation_requested_at remains the authoritative instruction
            # to cancel/observe the same remote operation after restart.
            run.status = "queued"
            run.error_code = None
            run.error_summary = None
            await session.commit()
            await NodeRunScheduler(session).enqueue_node_run_only(node_run_id)


async def recover_interrupted_director_turns(ctx: dict[str, Any]) -> dict[str, int]:
    """Fail-stop stale text submissions and expired turns after restart.

    This recovery path only reads/updates DirectorTurn coordination facts. It
    never invokes a text model, creates a NodeRun, or submits media.
    """

    from app.director.turn_service import DirectorTurnService
    from app.shared.db import (
        list_recoverable_director_turn_rls_scopes,
        set_rls_context,
    )

    # ARQ shallow-copies its context per job; initialize shared sweep state at
    # startup so cursor updates survive across cron invocations in this worker.
    ctx.setdefault("director_scan_state", {"cursor": None})
    factory = get_session_factory()
    recovered = 0
    unchanged = 0
    async with factory() as session:
        candidates = await list_recoverable_director_turn_rls_scopes(session, limit=50)
        for turn_id, scope in candidates:
            await set_rls_context(
                session,
                user_id=scope.user_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
            )
            try:
                service = DirectorTurnService(session)
                before = await service.get(project_id=scope.project_id, turn_id=turn_id)
                if before.runtime_execution_id is not None:
                    unchanged += 1
                    await session.rollback()
                    continue
                revision = before.revision
                after = await service.recover_interrupted(
                    project_id=scope.project_id,
                    turn_id=turn_id,
                )
                if after.revision != revision:
                    recovered += 1
                else:
                    unchanged += 1
                await session.commit()
            except Exception:  # noqa: BLE001 - one turn cannot block sibling recovery
                await session.rollback()
                logger.exception("Unable to recover DirectorTurn %s", turn_id)
    return {"recovered": recovered, "unchanged": unchanged}


async def reconcile_waiting_director_turns(ctx: dict[str, Any]) -> dict[str, int]:
    """Low-rate, browser-independent next-checkpoint reconciliation."""

    from app.access.models import Project
    from app.director.next_action import DirectorNextActionService
    from app.director.runtime.reconcile import DirectorRuntimeFactReconciler
    from app.director.turn_service import DirectorTurnService
    from app.shared.db import (
        list_reconcilable_director_turn_rls_scopes,
        set_rls_context,
    )
    from app.shared.errors import ConflictError

    factory = get_session_factory()
    reconciled = 0
    unchanged = 0
    failed = 0
    async with factory() as session:
        scan_state = ctx.setdefault("director_scan_state", {"cursor": None})
        cursor = scan_state["cursor"]
        candidates = await list_reconcilable_director_turn_rls_scopes(
            session, limit=50, after_turn_id=UUID(cursor) if cursor else None
        )
        # Stable keyset pagination advances past unchanged or invalid turns.
        # Restart begins a new sweep; reconciliation itself is idempotent.
        scan_state["cursor"] = str(candidates[-1][0]) if candidates else None
        for turn_id, scope in candidates:
            await set_rls_context(
                session,
                user_id=scope.user_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
            )
            try:
                project = await session.get(Project, scope.project_id)
                if project is None:
                    failed += 1
                    await session.rollback()
                    continue
                turn = await DirectorTurnService(session).get(
                    project_id=project.id,
                    turn_id=turn_id,
                )
                if turn.runtime_execution_id is not None:
                    wakeup = await DirectorRuntimeFactReconciler(session).reconcile(turn)
                    if wakeup is None:
                        unchanged += 1
                    else:
                        reconciled += 1
                    await session.commit()
                    continue
                revision = turn.revision
                result = await DirectorNextActionService(session).reconcile(
                    project=project,
                    turn_id=turn_id,
                )
                if result.turn_revision != revision:
                    reconciled += 1
                else:
                    unchanged += 1
                await session.commit()
            except ConflictError as exc:
                failed += 1
                if exc.details.get("code") == "DIRECTOR_TURN_LIMIT_REACHED":
                    await session.commit()
                else:
                    await session.rollback()
            except Exception:  # noqa: BLE001 - one turn cannot block sibling reconciliation
                failed += 1
                await session.rollback()
                logger.exception("Unable to reconcile DirectorTurn %s", turn_id)
    return {"reconciled": reconciled, "unchanged": unchanged, "failed": failed}


async def execute_node_run(ctx: dict[str, Any], node_run_id: str) -> dict[str, Any]:
    """Worker job: execute media NodeRun via product_path (Adapter OK here)."""
    from app.execution.composite_media import composite_inputs_pending
    from app.execution.models import NodeRun
    from app.execution.product_path import claim_media_node_run, execute_media_node_run
    from app.execution.runtime_invariants import (
        evaluate_required_dependencies,
        fail_run_for_dependency,
    )

    _ = ctx
    factory = get_session_factory()
    run_uuid = UUID(node_run_id)
    scope = None
    async with factory() as session:
        try:
            scope = await set_node_run_rls_context(session, node_run_id=run_uuid)
            if scope is None:
                return {"status": "failed", "error": "node_run not found"}
            run = await session.get(NodeRun, run_uuid)
            if run is None:
                return {"status": "failed", "error": "node_run not visible under RLS"}
            if run.status == "cancelled":
                return {"status": "cancelled", "node_run_id": node_run_id}
            dependency = await evaluate_required_dependencies(session, run=run)
            if dependency.action == "defer":
                raise Retry(defer=5)
            if dependency.action == "fail":
                await fail_run_for_dependency(
                    session,
                    run=run,
                    decision=dependency,
                )
                await session.commit()
                return {
                    "status": "failed",
                    "node_run_id": node_run_id,
                    "error_code": dependency.error_code,
                }
            if await composite_inputs_pending(session, run=run):
                raise Retry(defer=5)
            await claim_media_node_run(session, node_run_id=run_uuid)
            result = await execute_media_node_run(
                session,
                node_run_id=run_uuid,
                already_claimed=True,
            )
            terminal_status = run.status
            await session.commit()
            return {
                "status": terminal_status,
                "node_run_id": str(result.node_run_id),
                "artifact_id": str(result.artifact_id),
                "object_key": result.object_key,
                "content_hash": result.content_hash,
                "byte_size": result.byte_size,
                "identity_status": result.identity_status,
                "node_type": result.node_type,
            }
        except NodeRunAlreadyClaimedError:
            await session.rollback()
            return {"status": "already_claimed", "node_run_id": node_run_id}
        except ProviderTaskPendingError:
            await session.rollback()
            raise Retry(defer=5) from None
        except ProviderTaskCancelledError:
            await session.rollback()
            return {"status": "cancelled", "node_run_id": node_run_id}
        except ProviderRateLimitedError as exc:
            await session.rollback()
            retry_after = float(exc.details.get("retry_after_seconds") or 5.0)
            # Requeue the claimed run so the dispatcher re-enqueues it after
            # Retry-After (plan §11.2: 429 follows Retry-After, new attempt).
            try:
                async with factory() as s2:
                    if await set_node_run_rls_context(s2, node_run_id=run_uuid) is not None:
                        run2 = await s2.get(NodeRun, run_uuid)
                        if run2 is not None and run2.status == "running":
                            run2.status = "queued"
                            await s2.commit()
            except Exception:  # noqa: BLE001 - requeue must not mask the Retry
                pass
            raise Retry(defer=max(retry_after, 1.0)) from None
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Retry:
            await session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            # Fail-stop after a claimed Provider attempt. Failed runs are not
            # automatically requeued, so an ambiguous remote outcome cannot
            # trigger a duplicate submission.
            try:
                async with factory() as s2:
                    if await set_node_run_rls_context(s2, node_run_id=run_uuid) is None:
                        return {"status": "failed", "error": str(exc)[:300]}
                    run2 = await s2.get(NodeRun, run_uuid)
                    if run2 is not None and run2.status in {
                        "queued",
                        "running",
                        "cancel_requested",
                    }:
                        run2.status = "failed"
                        run2.error_code = _worker_failure_code(exc)
                        # Some transport errors have an empty str() (e.g. a bare
                        # TimeoutError). Record the exception class so a transient
                        # network failure is diagnosable instead of an empty summary.
                        message = str(exc).strip()
                        run2.error_summary = (
                            message[:500] if message else f"{type(exc).__name__} (no message)"
                        )
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
    from app.runtime.scheduler import NodeRunScheduler, RedisStreamPublisher

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        pub = RedisStreamPublisher(settings.redis_url)
        try:
            n = await NodeRunScheduler(session, publisher=pub).dispatch_pending(
                worker_id=str(ctx.get("job_id", "worker"))
            )
            return {"enqueued": n}
        finally:
            await pub.close()


JOB_FUNCTIONS = [
    health_ping,
    execute_node_run,
    dispatch_outbox,
]
