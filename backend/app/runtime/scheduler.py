"""Outbox publish + Arq enqueue only. Adapter execution is Worker-only."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from redis.asyncio import Redis, from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.execution.models import GraphNode, NodeRun
from app.shared.db import (
    NodeRunRlsScope,
    list_pending_outbox_event_rls_scopes,
    list_queued_node_run_rls_scopes,
    set_node_run_rls_context,
    set_rls_context,
)
from app.shared.errors import (
    NodeRunAlreadyClaimedError,
    NotFoundError,
    ProviderRateLimitedError,
    ProviderTaskPendingError,
    ValidationAppError,
)


def queue_scoped_job_id(
    *,
    queue_name: str,
    node_run_id: UUID,
    dispatch_generation: str | None = None,
) -> str:
    """Return an idempotency key that cannot leak across isolated Arq queues.

    Arq stores job definitions under a global Redis key. Reusing only the
    NodeRun id meant an old job key could survive after a formal stack switched
    to its commit-scoped queue: enqueue then returned ``None`` even though the
    current queue had no job to execute. Scoping the key to the target queue
    preserves idempotency within that queue while allowing recovery after a
    stack restart on a new source commit.
    """
    queue_fingerprint = hashlib.sha256(queue_name.encode("utf-8")).hexdigest()[:12]
    generation = f":{dispatch_generation}" if dispatch_generation else ""
    return f"node-run:{queue_fingerprint}:{node_run_id}{generation}"


def dispatch_source_commit() -> str | None:
    """Return the formal runtime commit used to isolate queued NodeRuns.

    Unit tests intentionally create historical fixture rows without a runtime
    binding, so they retain broad scheduling. The formal Compose runtime always
    provides a commit and therefore never replays rows from an earlier stack.
    """
    settings = get_settings()
    if settings.app_env == "test":
        return None
    return settings.source_commit.strip() or None


class RedisStreamPublisher(StreamPublisher):
    """Publish to Redis Streams. Formal path is fail-closed (no silent in-memory fallback)."""

    def __init__(self, redis_url: str) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._redis: Redis[Any] | None = None

    def _client(self) -> Redis[Any]:
        if self._redis is None:
            self._redis = from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def publish(self, topic: str, payload: dict[str, object]) -> str:
        try:
            client = self._client()
            fields = {k: str(v) if not isinstance(v, str) else v for k, v in payload.items()}
            msg_id = await client.xadd(f"dramaforge:stream:{topic}", fields)
            self.messages.append((topic, {**payload, "_stream_id": msg_id}))
            return str(msg_id)
        except Exception as exc:
            # APP_ENV=test only: allow in-memory publisher for unit tests without Redis.
            settings = get_settings()
            if settings.app_env == "test":
                return await super().publish(topic, payload)
            raise ValidationAppError(
                f"OUTBOX_PUBLISH_FAILED: Redis Stream write failed "
                f"({type(exc).__name__}: {exc}). Outbox must not be marked published."
            ) from exc

    async def close(self) -> None:
        """Release the Redis connection held by one dispatcher iteration."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None


class AgentRunScheduler:
    """API-safe scheduler: Outbox claim/publish + Arq enqueue. Never calls Adapters."""

    def __init__(
        self,
        session: AsyncSession,
        publisher: StreamPublisher | None = None,
    ) -> None:
        self._session = session
        self._dispatcher = OutboxDispatcher(session, publisher=publisher)
        self.enqueued_job_ids: list[str] = []

    async def dispatch_pending(
        self,
        *,
        worker_id: str = "scheduler",
        project_id: UUID | None = None,
    ) -> int:
        """Claim outbox + enqueue Arq jobs for queued NodeRuns (no Adapter here)."""
        count = 0
        event_scopes = await list_pending_outbox_event_rls_scopes(
            self._session,
            limit=20,
            project_id=project_id,
        )
        for event_scope in event_scopes:
            await set_rls_context(
                self._session,
                user_id=event_scope.user_id,
                workspace_id=event_scope.workspace_id,
                project_id=event_scope.project_id,
            )
            event = await self._dispatcher.claim_one_by_event_id(
                event_id=event_scope.event_id,
                worker_id=worker_id,
            )
            if event is None:
                await self._session.rollback()
                continue
            try:
                await self._dispatcher.publish_leased(event)
                await self._session.commit()
                count += 1
            except Exception as exc:  # noqa: BLE001
                try:
                    await self._dispatcher.fail_leased(event, error=str(exc))
                    await self._session.commit()
                except Exception:  # noqa: BLE001
                    await self._session.rollback()

        candidates = await list_queued_node_run_rls_scopes(
            self._session,
            limit=50,
            project_id=project_id,
            source_commit=dispatch_source_commit(),
        )
        for run_id, node_run_scope in candidates:
            try:
                await set_rls_context(
                    self._session,
                    user_id=node_run_scope.user_id,
                    workspace_id=node_run_scope.workspace_id,
                    project_id=node_run_scope.project_id,
                )
                job_id = await self._enqueue_node_run(run_id)
                await self._session.commit()
                self.enqueued_job_ids.append(job_id)
                count += 1
            except Exception as exc:  # noqa: BLE001
                await self._session.rollback()
                await set_rls_context(
                    self._session,
                    user_id=node_run_scope.user_id,
                    workspace_id=node_run_scope.workspace_id,
                    project_id=node_run_scope.project_id,
                )
                await self._mark_queue_failed(run_id, error=str(exc))
        return count

    async def enqueue_node_run_only(self, node_run_id: UUID) -> str:
        """Write Outbox, COMMIT, then enqueue Arq. Never executes Adapter.

        Order is intentional: Worker must never observe a Redis job before the
        NodeRun/Outbox rows are durable. On enqueue failure, NodeRun is marked
        failed with QUEUE_UNAVAILABLE (no silent 200+queued).
        """
        from datetime import UTC, datetime
        from uuid import uuid4

        from app.events.models import OutboxEvent
        from app.shared.db import set_node_run_rls_context
        from app.shared.enums import OutboxStatus

        if await set_node_run_rls_context(
            self._session,
            node_run_id=node_run_id,
        ) is None:
            raise NotFoundError("node_run not found")
        run = await self._session.get(NodeRun, node_run_id)
        if run is None:
            raise NotFoundError("node_run not found")
        # Durable Outbox fact before Arq (NodeRun → Outbox → commit → Arq)
        existing = await self._session.execute(
            select(OutboxEvent).where(
                OutboxEvent.project_id == run.project_id,
                OutboxEvent.topic == "node_run.enqueue",
            )
        )
        dispatch_generation = str(
            (run.input_snapshot or {}).get("dispatch_generation") or ""
        )
        has_enqueue_event = any(
            str((event.payload or {}).get("node_run_id")) == str(node_run_id)
            and str((event.payload or {}).get("dispatch_generation") or "")
            == dispatch_generation
            for event in existing.scalars().all()
        )
        if not has_enqueue_event:
            self._session.add(
                OutboxEvent(
                    event_id=uuid4(),
                    project_id=run.project_id,
                    topic="node_run.enqueue",
                    schema_version=1,
                    payload={
                        "node_run_id": str(node_run_id),
                        "status": run.status,
                        "project_id": str(run.project_id),
                        "dispatch_generation": dispatch_generation,
                    },
                    status=OutboxStatus.PENDING.value,
                    attempt_count=0,
                    next_attempt_at=datetime.now(UTC),
                )
            )
        await self._session.flush()
        # COMMIT first — eliminate flush-then-Redis race
        await self._session.commit()
        try:
            if await set_node_run_rls_context(
                self._session,
                node_run_id=node_run_id,
            ) is None:
                raise NotFoundError("node_run not found")
            job_id = await self._enqueue_node_run(node_run_id)
        except Exception as exc:
            await set_node_run_rls_context(
                self._session,
                node_run_id=node_run_id,
            )
            await self._mark_queue_failed(node_run_id, error=str(exc))
            raise
        return job_id

    async def _mark_queue_failed(self, node_run_id: UUID, *, error: str) -> None:
        run = await self._session.get(NodeRun, node_run_id)
        if run is None:
            return
        if run.status == "queued":
            run.status = "failed"
            run.error_code = "QUEUE_UNAVAILABLE"
            run.error_summary = error[:500]
            from datetime import UTC, datetime

            run.finished_at = datetime.now(UTC)
            await self._session.commit()

    async def _enqueue_node_run(self, node_run_id: UUID) -> str:
        """Enqueue on Redis/Arq. Fail closed — never return local:* as success."""
        import asyncio

        from arq import create_pool
        from arq.connections import RedisSettings

        settings = get_settings()
        run = await self._session.get(NodeRun, node_run_id)
        node = await self._session.get(GraphNode, run.graph_node_id) if run else None
        # Real media Providers are capacity-limited and must not be submitted as
        # a burst from the general I/O queue.
        queue_name = (
            settings.arq_heavy_queue_name
            if node and node.node_type in {"keyframe", "video", "voice", "composite"}
            else settings.arq_default_queue_name
        )
        stable_job_id = queue_scoped_job_id(
            queue_name=queue_name,
            node_run_id=node_run_id,
            dispatch_generation=(
                str(
                    (getattr(run, "input_snapshot", None) or {}).get(
                        "dispatch_generation"
                    )
                    or ""
                )
                or None
                if run is not None
                else None
            ),
        )

        async def _arq() -> str:
            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            try:
                job = await redis.enqueue_job(
                    "execute_node_run",
                    str(node_run_id),
                    _job_id=stable_job_id,
                    _queue_name=queue_name,
                )
                if job is None:
                    # Already enqueued with same job id — treat as success (idempotent)
                    return stable_job_id
                return str(job.job_id)
            finally:
                await redis.close()

        try:
            return await asyncio.wait_for(_arq(), timeout=8.0)
        except Exception as exc:
            raise ValidationAppError(
                f"QUEUE_UNAVAILABLE: Redis/Arq enqueue failed ({type(exc).__name__}: {exc}). "
                "NodeRun marked failed; start Redis + workers (docker compose up -d)."
            ) from exc


class WorkerRuntime:
    """Worker-side poller: executes queued NodeRuns via product_path (Adapter OK here)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rollback_if_active(self) -> None:
        """Clear only an active transaction; do not expire committed ORM state."""
        if self._session.in_transaction():
            await self._session.rollback()

    async def _commit_if_active(self) -> None:
        """Close a transaction opened while inspecting a terminal run."""
        if self._session.in_transaction():
            await self._session.commit()

    async def process_queued(self, *, limit: int = 20) -> int:
        from app.execution.composite_media import composite_inputs_pending
        from app.execution.product_path import (
            claim_media_node_run,
            execute_media_node_run,
        )
        from app.execution.runtime_invariants import (
            evaluate_required_dependencies,
            fail_run_for_dependency,
        )

        candidates = await list_queued_node_run_rls_scopes(self._session, limit=limit)
        n = 0
        deferred = candidates
        while deferred:
            next_deferred: list[tuple[UUID, NodeRunRlsScope]] = []
            progressed = False
            for run_id, scope in deferred:
                current: NodeRun | None = None
                try:
                    await set_rls_context(
                        self._session,
                        user_id=scope.user_id,
                        workspace_id=scope.workspace_id,
                        project_id=scope.project_id,
                    )
                    current = await self._session.get(NodeRun, run_id)
                    if current is None:
                        continue
                    dependency = await evaluate_required_dependencies(self._session, run=current)
                    if dependency.action == "defer":
                        next_deferred.append((run_id, scope))
                        continue
                    if dependency.action == "fail":
                        await fail_run_for_dependency(
                            self._session,
                            run=current,
                            decision=dependency,
                        )
                        await self._session.commit()
                        progressed = True
                        n += 1
                        continue
                    # Composite-specific additional check (media key matching)
                    if await composite_inputs_pending(self._session, run=current):
                        next_deferred.append((run_id, scope))
                        continue
                    await claim_media_node_run(self._session, node_run_id=run_id)
                    await execute_media_node_run(
                        self._session,
                        node_run_id=run_id,
                        already_claimed=True,
                    )
                    await self._session.commit()
                    progressed = True
                except NodeRunAlreadyClaimedError:
                    await self._rollback_if_active()
                    continue
                except ProviderTaskPendingError:
                    await self._rollback_if_active()
                    next_deferred.append((run_id, scope))
                    continue
                except ProviderRateLimitedError:
                    await self._rollback_if_active()
                    # Requeue the claimed run so a later dispatch retries after
                    # Retry-After (plan §11.2: 429 follows Retry-After).
                    if await set_node_run_rls_context(self._session, node_run_id=run_id) is None:
                        continue
                    current = await self._session.get(NodeRun, run_id)
                    if current is not None and current.status == "running":
                        current.status = "queued"
                        await self._session.flush()
                        await self._commit_if_active()
                    next_deferred.append((run_id, scope))
                    continue
                except Exception as exc:  # noqa: BLE001
                    # Product execution can commit a terminal Provider/validation
                    # result before raising so the boundary cannot erase it. A
                    # read after that commit still autobegins a transaction, and
                    # rolling it back would expire ORM objects owned by callers.
                    if current is not None and current.status not in {"queued", "running"}:
                        await self._commit_if_active()
                    else:
                        await self._rollback_if_active()
                    if await set_node_run_rls_context(self._session, node_run_id=run_id) is None:
                        continue
                    current = await self._session.get(NodeRun, run_id)
                    if current is not None and current.status in {"queued", "running"}:
                        current.status = "failed"
                        current.error_code = getattr(exc, "code", None) or "NODE_EXECUTION_FAILED"
                        current.error_summary = str(exc)[:500]
                        from datetime import UTC, datetime

                        current.finished_at = datetime.now(UTC)
                        await self._session.flush()
                    await self._commit_if_active()
                    progressed = True
                n += 1
            if not progressed:
                break
            deferred = next_deferred
        return n

    async def process_one(self, node_run_id: UUID) -> bool:
        from app.execution.product_path import (
            claim_media_node_run,
            execute_media_node_run,
        )
        from app.execution.runtime_invariants import (
            evaluate_required_dependencies,
            fail_run_for_dependency,
        )

        if await set_node_run_rls_context(self._session, node_run_id=node_run_id) is None:
            raise NotFoundError("node_run not found")
        current = await self._session.get(NodeRun, node_run_id)
        if current is None:
            raise NotFoundError("node_run not found")
        dependency = await evaluate_required_dependencies(self._session, run=current)
        if dependency.action == "defer":
            return False
        if dependency.action == "fail":
            await fail_run_for_dependency(
                self._session,
                run=current,
                decision=dependency,
            )
            await self._session.commit()
            return True
        try:
            await claim_media_node_run(self._session, node_run_id=node_run_id)
        except NodeRunAlreadyClaimedError:
            await self._rollback_if_active()
            return False
        try:
            await execute_media_node_run(
                self._session,
                node_run_id=node_run_id,
                already_claimed=True,
            )
        except ProviderTaskPendingError:
            await self._rollback_if_active()
            return False
        await self._session.commit()
        return True
