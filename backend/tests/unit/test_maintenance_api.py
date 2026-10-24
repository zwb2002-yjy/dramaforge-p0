"""Maintenance recovery API: Owner-only list and explicit per-item replay."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.access.models import User
from app.config import clear_settings_cache, get_settings
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.events.models import EventLog, OutboxDeadLetter, OutboxEvent
from app.events.outbox import StreamPublisher
from app.main import create_app
from app.maintenance import recovery_service
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.enums import OutboxStatus
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class _MemoryRedisPublisher(StreamPublisher):
    """In-memory stand-in for RedisStreamPublisher inside the API test."""

    async def close(self) -> None:  # pragma: no cover - nothing to release
        return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any]]:
    clear_settings_cache()
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _run(coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _run(_prepare())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    monkeypatch.setattr(
        recovery_service, "RedisStreamPublisher", lambda _url: _MemoryRedisPublisher()
    )
    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    _run(engine.dispose())


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _seed_failures(factory: Any, *, project_id: str) -> dict[str, str]:
    failed_at = datetime.now(UTC) - timedelta(minutes=5)
    project_uuid = UUID(project_id)
    ids: dict[str, str] = {"failed_at": failed_at.isoformat()}

    async def _insert() -> None:
        async with factory() as session:
            owner_id = (
                await session.execute(User.__table__.select().limit(1))
            ).first()[0]
            event = EventLog(
                project_id=project_uuid,
                aggregate_type="test",
                aggregate_id=uuid4(),
                event_type="test.event",
                schema_version=1,
                actor_id=owner_id,
                payload={},
            )
            session.add(event)
            await session.flush()
            inbox = DirectorInbox(
                project_id=project_uuid,
                consumer_id="director",
                event_id=event.event_id,
            )
            session.add(inbox)
            await session.flush()
            wakeup = DirectorWakeup(
                inbox_id=inbox.id,
                project_id=project_uuid,
                attempt_count=5,
                next_attempt_at=failed_at,
                dead_letter_at=failed_at,
                last_error="RuntimeError",
            )
            session.add(wakeup)
            outbox = OutboxEvent(
                event_id=uuid4(),
                project_id=project_uuid,
                topic="production.execution_changed",
                schema_version=1,
                payload={"notice": {"kind": "execution_changed"}},
                status=OutboxStatus.DEAD_LETTER.value,
                attempt_count=3,
                next_attempt_at=failed_at,
                last_error_summary="redis unavailable",
            )
            session.add(outbox)
            await session.flush()
            dead_letter = OutboxDeadLetter(
                outbox_event_id=outbox.id,
                event_id=outbox.event_id,
                project_id=project_uuid,
                topic=outbox.topic,
                payload=outbox.payload,
                attempt_count=3,
                last_error_summary="redis unavailable",
                dead_lettered_at=failed_at,
            )
            session.add(dead_letter)
            await session.commit()
            ids["wakeup_id"] = str(wakeup.inbox_id)
            ids["dead_letter_id"] = str(dead_letter.id)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_insert())
    finally:
        loop.close()
    return ids


def test_maintenance_api_replays_only_with_the_observed_failure(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"recovery-api-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Recovery Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    project = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"recovery-{uuid4().hex[:8]}",
            "aspect_ratio": "9:16",
            "budget_limit": "0",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    ids = _seed_failures(factory, project_id=project_id)
    listed = client.get("/api/v1/maintenance/recovery")
    assert listed.status_code == 200, listed.text
    items = {item["kind"]: item for item in listed.json()["items"]}
    assert set(items) == {"director_wakeup", "outbox_dead_letter"}

    wakeup_item = items["director_wakeup"]
    wakeup_replay = client.post(
        f"/api/v1/maintenance/director-wakeups/{ids['wakeup_id']}/replay",
        json={
            "project_id": project_id,
            "expected_dead_letter_at": wakeup_item["failed_at"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert wakeup_replay.status_code == 200, wakeup_replay.text
    assert wakeup_replay.json()["applied"] is True

    stale = client.post(
        f"/api/v1/maintenance/director-wakeups/{ids['wakeup_id']}/replay",
        json={
            "project_id": project_id,
            "expected_dead_letter_at": wakeup_item["failed_at"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    # Already replayed: the row is no longer actionable, so it is a no-op.
    assert stale.status_code == 200, stale.text
    assert stale.json()["applied"] is False

    dead_letter_item = items["outbox_dead_letter"]
    outbox_replay = client.post(
        f"/api/v1/maintenance/outbox/dead-letters/{ids['dead_letter_id']}/replay",
        json={"expected_dead_lettered_at": dead_letter_item["failed_at"]},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert outbox_replay.status_code == 200, outbox_replay.text
    assert outbox_replay.json()["applied"] is True

    # Nothing actionable is left, and the audit trail records the replay.
    remaining = client.get("/api/v1/maintenance/recovery")
    assert remaining.status_code == 200
    assert remaining.json()["items"] == []

    conflict = client.post(
        f"/api/v1/maintenance/outbox/dead-letters/{ids['dead_letter_id']}/replay",
        json={"expected_dead_lettered_at": datetime.now(UTC).isoformat()},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert conflict.status_code == 409, conflict.text
    assert "changed" in conflict.json()["detail"]
