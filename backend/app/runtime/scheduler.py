"""Outbox publish + Arq enqueue only. Adapter execution is Worker-only."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.execution.models import NodeRun
from app.shared.errors import NotFoundError, ValidationAppError


class RedisStreamPublisher(StreamPublisher):
    """Publish to Redis Streams. Formal path is fail-closed (no silent in-memory fallback)."""

    def __init__(self, redis_url: str) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._redis = None

    def _client(self):  # type: ignore[no-untyped-def]
        if self._redis is None:
            from redis.asyncio import from_url

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

    async def dispatch_pending(self, *, worker_id: str = "scheduler") -> int:
        """Claim outbox + enqueue Arq jobs for queued NodeRuns (no Adapter here)."""
        count = 0
        events = await self._dispatcher.claim_pending(worker_id=worker_id, limit=20)
        for ev in events:
            try:
                await self._dispatcher.publish_leased(ev)
                count += 1
            except Exception as exc:  # noqa: BLE001
                await self._dispatcher.fail_leased(ev, error=str(exc))

        result = await self._session.execute(
            select(NodeRun)
            .where(NodeRun.status == "queued")
            .order_by(NodeRun.created_at)
            .limit(50)
        )
        # Commit Outbox publish state before any Arq enqueue (Worker must see DB).
        await self._session.commit()

        for run in result.scalars().all():
            try:
                job_id = await self._enqueue_node_run(run.id)
                self.enqueued_job_ids.append(job_id)
                count += 1
            except Exception as exc:  # noqa: BLE001
                await self._mark_queue_failed(run.id, error=str(exc))
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
        from app.shared.enums import OutboxStatus

        run = await self._session.get(NodeRun, node_run_id)
        if run is None:
            raise NotFoundError("node_run not found")
        # Durable Outbox fact before Arq (NodeRun → Outbox → commit → Arq)
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
                },
                status=OutboxStatus.PENDING.value,
                next_attempt_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        # COMMIT first — eliminate flush-then-Redis race
        await self._session.commit()
        try:
            job_id = await self._enqueue_node_run(node_run_id)
        except Exception as exc:
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
        stable_job_id = f"node-run:{node_run_id}"

        async def _arq() -> str:
            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            try:
                job = await redis.enqueue_job(
                    "execute_node_run",
                    str(node_run_id),
                    _job_id=stable_job_id,
                    _queue_name=settings.arq_default_queue_name,
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
                "NodeRun marked failed; start Redis + workers (start_p0_wsl_stack.sh)."
            ) from exc


class WorkerRuntime:
    """Worker-side poller: executes queued NodeRuns via product_path (Adapter OK here)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def process_queued(self, *, limit: int = 20) -> int:
        from app.execution.product_path import execute_media_node_run

        result = await self._session.execute(
            select(NodeRun)
            .where(NodeRun.status == "queued")
            .order_by(NodeRun.created_at)
            .limit(limit)
        )
        n = 0
        for run in result.scalars().all():
            try:
                await execute_media_node_run(self._session, node_run_id=run.id)
                n += 1
            except Exception:
                n += 1
        await self._session.commit()
        return n

    async def process_one(self, node_run_id: UUID) -> None:
        from app.execution.product_path import execute_media_node_run

        await execute_media_node_run(self._session, node_run_id=node_run_id)
        await self._session.commit()
