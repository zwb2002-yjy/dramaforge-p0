"""Final Film HTTP fail-closed authorization and timeline-version tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.delivery.models import Export
from app.editing.models import EditSession
from app.execution.models import NodeRun
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def api() -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    clear_settings_cache()
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def run(coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    run(prepare())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    run(engine.dispose())


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"final-film-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Final Film Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": client.headers["X-Workspace-Id"],
            "name": "Final Film API Project",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _create_edit_session(client: TestClient, project_id: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/edit-sessions",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _bump_edit_version(
    factory: async_sessionmaker[AsyncSession], edit_session_id: str
) -> None:
    async with factory() as session:
        edit = await session.get(EditSession, UUID(edit_session_id))
        assert edit is not None
        edit.version = 2
        await session.commit()


async def _count_rows(
    factory: async_sessionmaker[AsyncSession], project_id: str
) -> tuple[int, int]:
    async with factory() as session:
        run_count = await session.scalar(
            select(func.count()).select_from(NodeRun).where(
                NodeRun.project_id == UUID(project_id)
            )
        )
        export_count = await session.scalar(
            select(func.count()).select_from(Export).where(
                Export.project_id == UUID(project_id)
            )
        )
        return int(run_count or 0), int(export_count or 0)


def test_final_film_routes_fail_closed_for_stale_timeline_and_non_owner(
    api: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = api
    _register(client)
    project_id = _create_project(client)
    edit_session_id = _create_edit_session(client, project_id)

    async def bump() -> None:
        await _bump_edit_version(factory, edit_session_id)

    asyncio.run(bump())
    stale = client.post(
        f"/api/v1/projects/{project_id}/final-film/prepare",
        json={"edit_session_id": edit_session_id, "expected_timeline_version": 1},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stale.status_code == 422, stale.text
    assert stale.json()["details"]["code"] == "TIMELINE_VERSION_MISMATCH"

    assert client.post("/api/v1/auth/logout").status_code == 204
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"final-film-non-owner-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Not Final Film Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    non_owner_workspace = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = non_owner_workspace
    csrf = _csrf(client)
    non_owner_prepare = client.post(
        f"/api/v1/projects/{project_id}/final-film/prepare",
        json={"edit_session_id": edit_session_id, "expected_timeline_version": 2},
        headers={CSRF_HEADER: csrf},
    )
    non_owner_render = client.post(
        f"/api/v1/projects/{project_id}/final-film/render",
        json={
            "edit_session_id": edit_session_id,
            "expected_timeline_version": 2,
            "name": "Forbidden Final Film",
        },
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "forbidden-final-film"},
    )
    assert non_owner_prepare.status_code in {403, 404}, non_owner_prepare.text
    assert non_owner_render.status_code in {403, 404}, non_owner_render.text

    async def count_rows() -> tuple[int, int]:
        return await _count_rows(factory, project_id)

    assert asyncio.run(count_rows()) == (0, 0)
