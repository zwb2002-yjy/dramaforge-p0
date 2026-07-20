"""Outbox publish + Arq enqueue only. Adapter execution is Worker-only."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.execution.models import NodeRun


class RedisStreamPublisher(StreamPublisher):
    """Publish to Redis Streams when redis client is available."""

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
        except Exception:
            return await super().publish(topic, payload)


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
        for run in result.scalars().all():
            job_id = await self._enqueue_node_run(run.id)
            self.enqueued_job_ids.append(job_id)
            count += 1
        await self._session.commit()
        return count

    async def enqueue_node_run_only(self, node_run_id: UUID) -> str:
        """Enqueue a single NodeRun for Worker; does not execute Adapter."""
        job_id = await self._enqueue_node_run(node_run_id)
        await self._session.commit()
        return job_id

    async def _enqueue_node_run(self, node_run_id: UUID) -> str:
        settings = get_settings()
        # Prefer fast local enqueue marker; Arq optional when redis responds quickly.
        try:
            import asyncio

            from arq import create_pool
            from arq.connections import RedisSettings

            async def _arq() -> str:
                redis = await create_pool(
                    RedisSettings.from_dsn(settings.redis_url, conn_timeout=0.3)
                )
                try:
                    job = await redis.enqueue_job(
                        "execute_node_run",
                        str(node_run_id),
                        _queue_name=settings.arq_default_queue_name,
                    )
                    return str(job.job_id if job else node_run_id)
                finally:
                    await redis.close()

            return await asyncio.wait_for(_arq(), timeout=0.5)
        except Exception:
            # Offline / no Redis: WorkerRuntime / arq worker picks up queued NodeRun
            return f"local:{node_run_id}"


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
