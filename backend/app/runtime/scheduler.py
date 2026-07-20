"""Outbox → Arq / in-process dispatch for queued NodeRuns."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.execution.models import NodeRun
from app.execution.product_path import execute_keyframe_node_run
from app.shared.enums import OutboxStatus


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
    """Dispatches pending Outbox and queued NodeRuns."""

    def __init__(
        self,
        session: AsyncSession,
        publisher: StreamPublisher | None = None,
    ) -> None:
        self._session = session
        self._dispatcher = OutboxDispatcher(session, publisher=publisher)

    async def dispatch_pending(self, *, worker_id: str = "scheduler") -> int:
        """Claim outbox + execute queued keyframe NodeRuns in-process (or enqueue Arq)."""
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
            .limit(20)
        )
        for run in result.scalars().all():
            try:
                await execute_keyframe_node_run(self._session, node_run_id=run.id)
                count += 1
            except Exception:
                # execute_keyframe_node_run already marks failed when possible
                count += 1
        await self._session.commit()
        return count

    async def dispatch_node_run(self, node_run_id: UUID) -> int:
        await execute_keyframe_node_run(self._session, node_run_id=node_run_id)
        await self._session.commit()
        return 1
