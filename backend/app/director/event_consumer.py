"""Independent Redis consumer: durable database receipt precedes stream ACK."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.director.inbox import DIRECTOR_CONSUMER_ID, receive_production_event
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError

PRODUCTION_STREAM = "dramaforge:stream:production.facts.v1"
logger = logging.getLogger(__name__)

_QUARANTINE = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending == 0 or pending[1][2] ~= ARGV[3] or pending[1][4] < 5 then
  return 0
end
redis.call('XADD', KEYS[2], '*', 'source_message_id', ARGV[2],
           'event_id', ARGV[4], 'error_type', ARGV[5])
redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
return 1
"""


class DirectorEventConsumer:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], redis: Redis[Any], *,
        consumer_name: str, reclaim_after_ms: int = 60000,
    ) -> None:
        self._factory = factory
        self._redis = redis
        self._consumer_name = consumer_name
        self._reclaim_after_ms = reclaim_after_ms
        self._claim_cursor = "0-0"

    async def receive(self, *, message_id: str, event_id: UUID) -> UUID:
        async with self._factory() as session:
            scopes = await session.execute(text(
                "SELECT owner_user_id, workspace_id, project_id "
                "FROM app.director_production_event_context(:event_id)"
            ), {"event_id": event_id})
            scope = scopes.mappings().one_or_none()
            if scope is None:
                raise NotFoundError("Production event ownership not found")
            await set_rls_context(
                session, user_id=scope["owner_user_id"], workspace_id=scope["workspace_id"],
                project_id=scope["project_id"],
            )
            inbox_id = await receive_production_event(
                session, project_id=scope["project_id"], event_id=event_id,
            )
            await session.commit()
        # If ACK fails, redelivery finds the committed receipt. No queue job
        # is necessary to preserve the wakeup; the dispatcher scans the DB.
        await self._redis.xack(  # type: ignore[no-untyped-call]
            PRODUCTION_STREAM, DIRECTOR_CONSUMER_ID, message_id,
        )
        return inbox_id

    async def poll_once(self) -> int:
        try:
            await self._redis.xgroup_create(
                PRODUCTION_STREAM, DIRECTOR_CONSUMER_ID, id="0-0", mkstream=True,
            )
        except ResponseError as exc:
            if not str(exc).startswith("BUSYGROUP"):
                raise
        reclaimed = await self._redis.xautoclaim(
            PRODUCTION_STREAM, DIRECTOR_CONSUMER_ID, self._consumer_name,
            min_idle_time=self._reclaim_after_ms, start_id=self._claim_cursor, count=50,
        )
        self._claim_cursor = reclaimed[0]
        messages = list(reclaimed[1])
        batches = await self._redis.xreadgroup(
            DIRECTOR_CONSUMER_ID, self._consumer_name,
            {PRODUCTION_STREAM: ">"}, count=50, block=None if messages else 1000,
        )
        messages.extend(message for _stream, batch in batches for message in batch)
        completed = 0
        failure: Exception | None = None
        for message_id, fields in messages:
            event_reference = ""
            try:
                raw_id = fields.get("event_id", fields.get(b"event_id"))
                if isinstance(raw_id, bytes):
                    raw_id = raw_id.decode("ascii")
                parsed_id = UUID(str(raw_id))
                event_reference = str(parsed_id)
                await self.receive(message_id=message_id, event_id=parsed_id)
                completed += 1
            except Exception as exc:
                if isinstance(exc, (ValueError, NotFoundError)):
                    archived = await self._redis.eval(  # type: ignore[no-untyped-call]
                        _QUARANTINE, 2, PRODUCTION_STREAM,
                        f"{PRODUCTION_STREAM}:director-dead-letter", DIRECTOR_CONSUMER_ID,
                        message_id, self._consumer_name, event_reference, type(exc).__name__,
                    )
                    if archived:
                        completed += 1
                        continue
                # A bad event must not prevent siblings from reaching durable
                # intake. Failed deliveries remain pending for recovery.
                failure = exc
                logger.warning("Director intake failed for message %s (%s)",
                               message_id, type(exc).__name__)
        if failure is not None and completed == 0:
            raise failure
        return completed
