"""Outbox claim / publish / dead-letter / durable idempotent human replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.models import OutboxDeadLetter, OutboxEvent
from app.shared.enums import OutboxStatus
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.observability import (
    OUTBOX_DEAD_LETTER_TOTAL,
    OUTBOX_PENDING,
    OUTBOX_PUBLISHED_TOTAL,
    OUTBOX_REPLAY_TOTAL,
)


class StreamPublisher:
    """Port for Redis Streams; in-memory fake used when Redis unavailable."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, object]]] = []

    async def publish(self, topic: str, payload: dict[str, object]) -> str:
        msg_id = f"{len(self.messages) + 1}-0"
        self.messages.append((topic, {**payload, "_stream_id": msg_id}))
        return msg_id


class OutboxDispatcher:
    def __init__(
        self,
        session: AsyncSession,
        publisher: StreamPublisher | None = None,
        *,
        max_attempts: int = 3,
        lease_seconds: int = 30,
    ) -> None:
        self._session = session
        self._publisher = publisher or StreamPublisher()
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    async def reclaim_expired_leases(self, *, now: datetime | None = None) -> int:
        """Return expired LEASED rows to PENDING for retry."""
        ts = now or datetime.now(UTC)
        result = await self._session.execute(
            select(OutboxEvent).where(
                OutboxEvent.status == OutboxStatus.LEASED.value,
                OutboxEvent.leased_until.is_not(None),
                OutboxEvent.leased_until < ts,
            )
        )
        n = 0
        for row in result.scalars().all():
            row.status = OutboxStatus.PENDING.value
            row.locked_by = None
            row.leased_until = None
            row.next_attempt_at = ts
            row.last_error_summary = "lease_expired_reclaimed"
            n += 1
        if n:
            await self._session.flush()
        return n

    async def claim_pending(self, *, worker_id: str, limit: int = 10) -> list[OutboxEvent]:
        """Concurrent-safe claim: reclaim expired leases, then FOR UPDATE SKIP LOCKED."""
        now = datetime.now(UTC)
        await self.reclaim_expired_leases(now=now)

        # Prefer row-level locking when the dialect supports it (PostgreSQL).
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .where(OutboxEvent.next_attempt_at <= now)
            .order_by(OutboxEvent.created_at)
            .limit(limit)
        )
        bind = self._session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "") or ""
        if dialect.startswith("postgres"):
            stmt = stmt.with_for_update(skip_locked=True)

        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        leased_until = now + timedelta(seconds=self._lease_seconds)
        for row in rows:
            row.status = OutboxStatus.LEASED.value
            row.locked_by = worker_id
            row.leased_until = leased_until
            row.attempt_count += 1
        await self._session.flush()
        return rows

    async def publish_leased(self, event: OutboxEvent) -> None:
        if event.status == OutboxStatus.PUBLISHED.value:
            return
        if event.status != OutboxStatus.LEASED.value:
            raise ValidationAppError("only leased outbox events can be published")
        stream_id = await self._publisher.publish(
            event.topic,
            {
                "event_id": str(event.event_id),
                "payload": event.payload,
                "schema_version": event.schema_version,
            },
        )
        event.status = OutboxStatus.PUBLISHED.value
        event.published_at = datetime.now(UTC)
        event.locked_by = None
        event.leased_until = None
        event.last_error_summary = f"stream_id={stream_id}"
        OUTBOX_PUBLISHED_TOTAL.inc()
        await self._session.flush()

    async def fail_leased(self, event: OutboxEvent, *, error: str) -> OutboxDeadLetter | None:
        if event.status != OutboxStatus.LEASED.value:
            raise ValidationAppError("only leased outbox events can fail")
        event.last_error_summary = error[:500]
        if event.attempt_count >= self._max_attempts:
            event.status = OutboxStatus.DEAD_LETTER.value
            event.locked_by = None
            event.leased_until = None
            dl = OutboxDeadLetter(
                outbox_event_id=event.id,
                event_id=event.event_id,
                project_id=event.project_id,
                topic=event.topic,
                payload=event.payload,
                attempt_count=event.attempt_count,
                last_error_summary=error[:500],
            )
            self._session.add(dl)
            OUTBOX_DEAD_LETTER_TOTAL.inc()
            await self._session.flush()
            return dl
        event.status = OutboxStatus.PENDING.value
        event.locked_by = None
        event.leased_until = None
        event.next_attempt_at = datetime.now(UTC)
        await self._session.flush()
        return None

    async def _published_by_event_id(self, event_id: UUID) -> OutboxEvent | None:
        """Durable singleflight: published row wins across dispatcher instances."""
        result = await self._session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_id == event_id,
                OutboxEvent.status == OutboxStatus.PUBLISHED.value,
            )
        )
        return result.scalar_one_or_none()

    async def human_replay_dead_letter(
        self, dead_letter_id: UUID, *, operator: str
    ) -> OutboxEvent:
        """Replay a dead letter; never double-publish if event_id already published."""
        result = await self._session.execute(
            select(OutboxDeadLetter).where(OutboxDeadLetter.id == dead_letter_id)
        )
        dl = result.scalar_one_or_none()
        if dl is None:
            raise NotFoundError("dead letter not found")

        published = await self._published_by_event_id(dl.event_id)
        if published is not None:
            OUTBOX_REPLAY_TOTAL.labels(result="idempotent").inc()
            return published

        existing = await self._session.execute(
            select(OutboxEvent).where(OutboxEvent.id == dl.outbox_event_id)
        )
        event = existing.scalar_one_or_none()
        if event is None:
            event = OutboxEvent(
                id=dl.outbox_event_id,
                event_id=dl.event_id,
                project_id=dl.project_id,
                topic=dl.topic,
                schema_version=1,
                payload=dl.payload,
                status=OutboxStatus.PENDING.value,
                attempt_count=0,
            )
            self._session.add(event)
        elif event.status == OutboxStatus.PUBLISHED.value:
            OUTBOX_REPLAY_TOTAL.labels(result="idempotent").inc()
            return event
        else:
            # Only reset non-published rows (pending/leased/dead_letter)
            event.status = OutboxStatus.PENDING.value
            event.attempt_count = 0
            event.locked_by = None
            event.leased_until = None
            event.published_at = None
            event.next_attempt_at = datetime.now(UTC)
            event.last_error_summary = f"replay_by={operator}"
        await self._session.flush()

        # Re-check race: another worker may have published
        published = await self._published_by_event_id(dl.event_id)
        if published is not None:
            OUTBOX_REPLAY_TOTAL.labels(result="idempotent").inc()
            return published

        # Lease and publish ONLY this dead letter's outbox row — never bulk-claim siblings.
        target = await self._claim_one(
            event_id=dl.event_id, worker_id=f"replay:{operator}"
        )
        if target is None:
            published = await self._published_by_event_id(dl.event_id)
            if published is not None:
                OUTBOX_REPLAY_TOTAL.labels(result="idempotent").inc()
                return published
            raise ValidationAppError("failed to claim replayed outbox event")
        await self.publish_leased(target)
        OUTBOX_REPLAY_TOTAL.labels(result="applied").inc()
        return target

    async def _claim_one(self, *, event_id: UUID, worker_id: str) -> OutboxEvent | None:
        """Lease a single pending outbox row by event_id without touching siblings."""
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.event_id == event_id)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .where(OutboxEvent.next_attempt_at <= now)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = OutboxStatus.LEASED.value
        row.locked_by = worker_id
        row.leased_until = now + timedelta(seconds=self._lease_seconds)
        row.attempt_count += 1
        await self._session.flush()
        return row

    async def pending_count(self) -> int:
        result = await self._session.execute(
            select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.PENDING.value)
        )
        n = len(list(result.scalars().all()))
        OUTBOX_PENDING.set(n)
        return n
