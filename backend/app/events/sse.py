"""In-process SSE event buffer with Last-Event-ID resume."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from redis.asyncio import Redis, from_url

from app.shared.observability import SSE_RECONNECT_TOTAL

logger = logging.getLogger(__name__)
PRODUCTION_FACTS_STREAM = "dramaforge:stream:production.facts.v1"


@dataclass(frozen=True)
class SseEnvelope:
    id: str
    event: str
    data: dict[str, object]


class SseHub:
    """Project-scoped ring buffer of SSE envelopes (no live Redis required)."""

    def __init__(self, *, capacity: int = 1000) -> None:
        self._capacity = capacity
        self._events: deque[SseEnvelope] = deque(maxlen=capacity)
        self._waiters: list[asyncio.Event] = []

    def publish(self, *, event: str, data: dict[str, object]) -> SseEnvelope:
        envelope = SseEnvelope(id=str(uuid4()), event=event, data=data)
        self._events.append(envelope)
        for waiter in list(self._waiters):
            waiter.set()
        return envelope

    def since(self, last_event_id: str | None) -> list[SseEnvelope]:
        if not last_event_id:
            return list(self._events)
        out: list[SseEnvelope] = []
        seen = False
        for env in self._events:
            if seen:
                out.append(env)
            elif env.id == last_event_id:
                seen = True
        if not seen:
            # Unknown id: replay full buffer (safe for critical events + snapshot re-fetch)
            return list(self._events)
        return out

    async def stream(
        self,
        *,
        last_event_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AsyncIterator[SseEnvelope]:
        """Yield only the selected workspace's explicitly scoped envelopes."""
        if last_event_id:
            SSE_RECONNECT_TOTAL.inc()
        for env in self.since(last_event_id):
            if workspace_id is None or str(env.data.get("workspace_id")) == workspace_id:
                yield env
        cursor = self._events[-1].id if self._events else last_event_id
        while True:
            waiter = asyncio.Event()
            self._waiters.append(waiter)
            try:
                await waiter.wait()
            finally:
                self._waiters.remove(waiter)
            for env in self.since(cursor):
                cursor = env.id
                if workspace_id is None or str(env.data.get("workspace_id")) == workspace_id:
                    yield env


def format_sse(envelope: SseEnvelope) -> str:
    payload = json.dumps(envelope.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {envelope.id}\nevent: {envelope.event}\ndata: {payload}\n\n"


# Process-wide hub for BOOT/S1 local path; S3 may bind per-project Redis Streams.
default_sse_hub = SseHub()


class RedisSseBridge:
    """Fan durable production facts from the dispatcher into this API process."""

    def __init__(self, redis_url: str, *, hub: SseHub = default_sse_hub) -> None:
        self._redis: Redis[str] = from_url(redis_url, decode_responses=True)
        self._hub = hub
        self._last_id = "0-0"

    async def run_forever(self) -> None:
        while True:
            try:
                batches = await self._redis.xread(
                    {PRODUCTION_FACTS_STREAM: self._last_id}, count=100, block=1000
                )
                for _stream, messages in batches:
                    for message_id, fields in messages:
                        self._last_id = str(message_id)
                        self._publish_stream_message(fields)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - Redis recovery is best effort
                logger.warning("sse_redis_bridge_poll_failed", exc_info=True)
                await asyncio.sleep(1)

    def _publish_stream_message(self, fields: dict[str, str]) -> None:
        payload: object = {}
        raw_payload = fields.get("payload")
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                logger.warning("sse_redis_bridge_invalid_payload")
                return
        if not isinstance(payload, dict):
            logger.warning("sse_redis_bridge_payload_not_object")
            return

        workspace_id = fields.get("workspace_id")
        if not workspace_id:
            logger.warning("sse_redis_bridge_missing_workspace")
            return
        project_id = payload.get("project_id")
        self._hub.publish(
            event="production.facts.v1",
            data={
                "event_id": fields.get("event_id"),
                "topic": "production.facts.v1",
                "schema_version": int(fields.get("schema_version", "1")),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "payload": payload,
            },
        )

    async def close(self) -> None:
        await self._redis.close()
