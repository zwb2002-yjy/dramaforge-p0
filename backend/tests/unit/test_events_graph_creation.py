"""S1.3–S1.5: outbox co-write, graph immutability, start_project no providers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access import models as _access_models  # noqa: F401
from app.events import models as _event_models  # noqa: F401
from app.events.models import EventLog, OutboxEvent
from app.events.service import EventService
from app.production import models as _prod_models  # noqa: F401
from app.production.models import (
    GraphVersion,
    assert_graph_version_mutable,
    definition_hash,
)
from app.shared.base import Base
from app.shared.enums import GraphStatus
from app.shared.errors import ValidationAppError
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_event_and_outbox_same_flush() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        # minimal org/user/project FKs optional when project_id null
        log, outbox = await EventService(session).append_with_outbox(
            project_id=None,
            aggregate_type="project",
            aggregate_id=uuid4(),
            event_type="test.event",
            topic="test.topic",
            payload={"k": "v"},
        )
        await session.commit()
        assert log.event_id == outbox.event_id
        logs = (await session.execute(select(EventLog))).scalars().all()
        outs = (await session.execute(select(OutboxEvent))).scalars().all()
        assert len(logs) == 1
        assert len(outs) == 1
        assert outs[0].status == "pending"
    await engine.dispose()


@pytest.mark.asyncio
async def test_published_graph_version_immutable() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    body: dict[str, object] = {"nodes": []}
    version = GraphVersion(
        graph_id=uuid4(),
        version_number=1,
        status=GraphStatus.PUBLISHED.value,
        definition_hash=definition_hash(body),
        definition=body,
    )
    with pytest.raises(ValidationAppError):
        assert_graph_version_mutable(version)
    draft_body: dict[str, object] = {}
    draft = GraphVersion(
        graph_id=uuid4(),
        version_number=1,
        status=GraphStatus.DRAFT.value,
        definition_hash=definition_hash(draft_body),
        definition=draft_body,
    )
    assert_graph_version_mutable(draft)
    await engine.dispose()


def _auth_org(client: TestClient) -> str:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "creator@example.com",
            "password": "password123",
            "display_name": "Creator",
        },
    )
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    org = client.post(
        "/api/v1/organizations",
        json={"name": "CreateOrg"},
        headers={CSRF_HEADER: csrf},
    )
    return org.json()["id"]


def test_start_project_zero_text_providers(client: TestClient) -> None:
    org_id = _auth_org(client)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = client.post(
        "/api/v1/creation/start-project",
        json={
            "organization_id": org_id,
            "name": "QuickStart",
            "aspect_ratio": "9:16",
            "experience_mode": "quick",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text_provider_operations"] == 0
    assert body["experience_mode"] == "quick"
    assert client.get(f"/api/v1/projects/{body['project_id']}").status_code == 200
