"""In-process SSE event buffer with Last-Event-ID resume."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from app.shared.observability import SSE_RECONNECT_TOTAL


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
        self, *, last_event_id: str | None = None
    ) -> AsyncIterator[SseEnvelope]:
        if last_event_id:
            SSE_RECONNECT_TOTAL.inc()
        for env in self.since(last_event_id):
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
                yield env
                cursor = env.id


def format_sse(envelope: SseEnvelope) -> str:
    payload = json.dumps(envelope.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {envelope.id}\nevent: {envelope.event}\ndata: {payload}\n\n"


# Process-wide hub for BOOT/S1 local path; S3 may bind per-project Redis Streams.
default_sse_hub = SseHub()
