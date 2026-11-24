"""Recover upload keys journaled before Final Film object-store writes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.shared.db import get_session_factory, set_node_run_rls_context
from app.shared.observability import FINAL_FILM_CLEANUP_FAILURES
from app.storage.minio_store import ObjectStore, get_object_store

logger = logging.getLogger(__name__)
UPLOAD_LEASE = timedelta(minutes=31)


async def cleanup_final_film_uploads(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore,
) -> int:
    """Delete only journaled objects with no Artifact; retry failures next sweep.

    A stale local attempt is first fenced by its persisted operation status.
    Object IO happens after commit. Successful deliverables, including artifacts
    reused by a later export, are always retained. An expired/cancelled caller
    does not prove its storage write stopped: keep its keys until the writer
    confirms every put returned, so a late remote write remains discoverable.
    """
    if await set_node_run_rls_context(session, node_run_id=node_run_id) is None:
        await session.rollback()
        return 0
    operation = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == node_run_id,
            ProviderOperation.operation_kind == "final_film.compose",
        )
        .with_for_update(skip_locked=True)
    )
    if operation is None:
        await session.rollback()
        return 0
    keys = (operation.request_summary or {}).get("upload_objects")
    if not isinstance(keys, list) or not keys:
        await session.rollback()
        return 0
    run = await session.get(NodeRun, node_run_id)
    if run is None:
        await session.rollback()
        return 0
    if operation.status == "submission_started":
        started = operation.submitted_at or operation.created_at
        if started.replace(tzinfo=started.tzinfo or UTC) > datetime.now(UTC) - UPLOAD_LEASE:
            await session.rollback()
            return 0
        operation.status = run.status = "failed"
        operation.error_code = run.error_code = "FINAL_FILM_ATTEMPT_EXPIRED"
        operation.error_summary = run.error_summary = "Interrupted local Final Film upload"
        operation.completed_at = run.finished_at = datetime.now(UTC)
    elif operation.status not in {"succeeded", "failed", "cancelled"}:
        await session.rollback()
        return 0
    uploads_finished = (
        operation.status == "succeeded" or operation.request_summary.get("uploads_finished") is True
    )
    prefix = f"projects/{run.project_id}/final-film/{run.id}/"
    safe_keys = [
        key
        for key in keys
        if isinstance(key, str) and key.startswith(prefix) and key.endswith((".mp4", ".srt"))
    ]
    referenced = set(
        (
            await session.scalars(
                select(Artifact.object_key).where(Artifact.object_key.in_(safe_keys))
            )
        ).all()
    )
    # Rotate unresolved writers through the bounded scanner instead of letting
    # the oldest interrupted operations monopolize its first 50 slots.
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    failures = []
    deleted = 0
    for key in safe_keys:
        if key in referenced:
            continue
        try:
            await store.delete_bytes(object_key=key)
            deleted += 1
        except Exception:
            FINAL_FILM_CLEANUP_FAILURES.inc()
            logger.warning("final_film_upload_cleanup_failed run=%s", node_run_id, exc_info=True)
            failures.append(key)
    await set_node_run_rls_context(session, node_run_id=node_run_id)
    await session.refresh(operation, with_for_update=True)
    if uploads_finished:
        cleared = set(safe_keys) - set(failures)
        current_keys = operation.request_summary.get("upload_objects", [])
        if not isinstance(current_keys, list):
            current_keys = []
        operation.request_summary = {
            **operation.request_summary,
            "upload_objects": [
                key for key in current_keys if not isinstance(key, str) or key not in cleared
            ],
        }
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return deleted


async def sweep_final_film_uploads(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Bounded maintenance; the database scanner exposes only ownership IDs."""
    factory = session_factory or get_session_factory()
    async with factory() as session:
        ids = (
            await session.scalars(
                text("SELECT node_run_id FROM app.final_film_upload_contexts(50)")
            )
        ).all()
        await session.rollback()
        for node_run_id in ids:
            try:
                await cleanup_final_film_uploads(
                    session,
                    node_run_id=node_run_id,
                    store=await asyncio.to_thread(get_object_store),
                )
            except Exception:
                await session.rollback()
                FINAL_FILM_CLEANUP_FAILURES.inc()
                logger.warning("final_film_upload_sweep_failed run=%s", node_run_id, exc_info=True)
