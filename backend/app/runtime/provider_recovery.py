"""Bounded persisted Provider reconciliation shared by dispatcher and worker startup.

This module owns no worker or service. Its caller owns the lifecycle and scan
state; all admission still goes through the existing Scheduler and Outbox.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.db import get_session_factory
from app.shared.rls_scopes import PROVIDER_RECOVERY_LEASE

logger = logging.getLogger(__name__)

PROVIDER_RECOVERY_BATCH_SIZE = 50
PROVIDER_RECOVERY_TIMEOUT_SECONDS = 20


def _older_than(value: datetime | None, cutoff: datetime) -> bool:
    return value is not None and value.replace(tzinfo=value.tzinfo or UTC) < cutoff


def provider_attempt_is_active(started_at: datetime | None, *, now: datetime) -> bool:
    """A cooperative yield clears started_at; created_at is never an active lease."""
    return started_at is not None and not _older_than(started_at, now - PROVIDER_RECOVERY_LEASE)


async def recover_interrupted_provider_jobs(
    ctx: dict[str, Any],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, int]:
    """Bounded startup/periodic reconciliation of persisted remote identities.

    Never reset a running task or rotate its dispatch generation: the scheduler's
    stable Arq ID dedupes active/deferred jobs and retained results. The next sweep
    can retry that same ID after retention/queue failure without another create.
    """
    from sqlalchemy import select

    from app.execution.models import NodeRun, ProviderOperation
    from app.runtime.scheduler import NodeRunScheduler
    from app.shared.db import (
        list_resumable_provider_node_run_rls_scopes,
        set_rls_context,
    )

    # One cursor belongs to each caller lifecycle; shallow-copied startup contexts
    # also retain it. Advance past *attempted* rows, including errors/locks.
    state = ctx.setdefault("provider_recovery_scan_state", {"cursor": None, "busy": False})
    counts = {"scanned": 0, "resumed": 0, "unknown": 0, "failed": 0, "timed_out": 0}
    if state["busy"]:
        return counts
    state["busy"] = True
    cutoff = datetime.now(UTC) - PROVIDER_RECOVERY_LEASE
    try:
        async with asyncio.timeout(PROVIDER_RECOVERY_TIMEOUT_SECONDS):
            factory = session_factory if session_factory is not None else get_session_factory()
            async with factory() as session:
                cursor = state["cursor"]
                candidates = await list_resumable_provider_node_run_rls_scopes(
                    session,
                    limit=PROVIDER_RECOVERY_BATCH_SIZE,
                    source_commit=None,
                    after_node_run_id=UUID(cursor) if cursor else None,
                    stale_before=cutoff,
                )
                for node_run_id, scope in candidates:
                    state["cursor"] = str(node_run_id)
                    counts["scanned"] += 1
                    try:
                        await set_rls_context(
                            session,
                            user_id=scope.user_id,
                            workspace_id=scope.workspace_id,
                            project_id=scope.project_id,
                        )
                        run = await session.scalar(
                            select(NodeRun)
                            .where(NodeRun.id == node_run_id)
                            .with_for_update(skip_locked=True)
                            .execution_options(populate_existing=True)
                        )
                        if (
                            run is None
                            or run.status not in {"running", "cancel_requested"}
                            or not _older_than(run.started_at or run.created_at, cutoff)
                        ):
                            await session.rollback()
                            continue
                        latest_operation_id = (
                            select(ProviderOperation.id)
                            .where(
                                ProviderOperation.node_run_id == node_run_id,
                                ProviderOperation.execution_path_version == "unified-v1",
                            )
                            .order_by(
                                ProviderOperation.attempt_no.desc(),
                                ProviderOperation.created_at.desc(),
                            )
                            .limit(1)
                            .scalar_subquery()
                        )
                        operation = await session.scalar(
                            select(ProviderOperation)
                            .where(ProviderOperation.id == latest_operation_id)
                            .with_for_update(skip_locked=True)
                            .execution_options(populate_existing=True)
                        )
                        if operation is None or not _older_than(
                            operation.last_polled_at or operation.submitted_at
                            or operation.created_at,
                            cutoff,
                        ):
                            await session.rollback()
                            continue
                        if operation.provider_operation_id is None:
                            if operation.status == "submission_started" and _older_than(
                                operation.created_at, cutoff
                            ):
                                operation.status = "unknown_submission"
                                operation.error_code = "PROVIDER_SUBMISSION_UNKNOWN"
                                operation.error_summary = (
                                    "Interrupted submission has no remote identity; "
                                    "do not resubmit."
                                )
                                run.status = "failed"
                                run.error_code = operation.error_code
                                run.error_summary = operation.error_summary
                                run.finished_at = operation.completed_at = datetime.now(UTC)
                                await session.commit()
                                counts["unknown"] += 1
                            else:
                                await session.rollback()
                            continue
                        if operation.status not in {
                            "submitted", "running", "timed_out", "cancel_requested",
                        }:
                            await session.rollback()
                            continue
                        # Hold the NodeRun lock through the scheduler's Outbox
                        # commit. Overlapping sweeps share one durable event and
                        # one queue-scoped job ID, even if enqueue later fails.
                        await NodeRunScheduler(session).enqueue_node_run_only(node_run_id)
                        await session.commit()
                        counts["resumed"] += 1
                    except Exception:  # noqa: BLE001 - one row must not starve the tail
                        await session.rollback()
                        counts["failed"] += 1
                        logger.exception("Unable to recover Provider NodeRun %s", node_run_id)
                if len(candidates) < PROVIDER_RECOVERY_BATCH_SIZE:
                    # Wrap even when earlier UUIDs only became stale this pass.
                    state["cursor"] = None
    except TimeoutError:
        counts["timed_out"] = 1
        logger.warning("Provider recovery sweep reached its time bound")
    finally:
        state["busy"] = False
    return counts
