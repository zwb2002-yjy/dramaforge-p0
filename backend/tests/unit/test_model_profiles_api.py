"""Model-profile API tests (spec §34–§37) through the real HTTP surface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
def api() -> Iterator[tuple[TestClient, Any]]:
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

    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    _run(engine.dispose())


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register(client: TestClient) -> str:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"mp-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "MP Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _create_project(client: TestClient, workspace_id: str) -> str:
    project = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "MPProject",
            "aspect_ratio": "9:16",
            "budget_limit": "50.00",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code in (200, 201), project.text
    return str(project.json()["id"])


def test_model_slots_api(api: tuple[TestClient, Any]) -> None:
    client, _ = api
    workspace_id = _register(client)
    assert workspace_id
    slots = client.get("/api/v1/model-slots")
    assert slots.status_code == 200, slots.text
    ids = [s["id"] for s in slots.json()]
    assert "planning.brief" in ids
    assert "planning.script" in ids
    assert "visual.keyframe" in ids
    assert "video.shot" in ids
    script = next(s for s in slots.json() if s["id"] == "planning.script")
    assert script["capabilities"] == ["text.generate"]


def test_workspace_profile_crud_and_simple_mode(api: tuple[TestClient, Any]) -> None:
    client, _ = api
    workspace_id = _register(client)
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/model-profiles",
        json={
            "name": "默认方案",
            "bindings": {"visual.keyframe": {"model_id": "agnes/agnes-image-2.1-flash"}},
            "is_default": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["version"] == 1
    assert profile["bindings"]["visual.keyframe"]["model_id"] == "agnes/agnes-image-2.1-flash"

    # simple mode batch patch (LLM / Image / Video → slot groups)
    simple = client.post(
        f"/api/v1/workspaces/{workspace_id}/model-profiles/{profile['id']}/simple-mode",
        json={
            "llm_model_id": "litellm/text-llm",
            "image_model_id": "agnes/agnes-image-2.1-flash",
            "expected_version": 1,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert simple.status_code == 200, simple.text
    updated = simple.json()
    assert updated["version"] == 2
    assert updated["bindings"]["planning.brief"]["model_id"] == "litellm/text-llm"
    assert updated["bindings"]["visual.keyframe"]["model_id"] == "agnes/agnes-image-2.1-flash"

    # version conflict
    conflict = client.put(
        f"/api/v1/workspaces/{workspace_id}/model-profiles/{profile['id']}",
        json={"name": "改名", "expected_version": 1},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["details"]["code"] == "MODEL_PROFILE_VERSION_CONFLICT"


def test_workspace_profile_validation_rejects_capability_mismatch(
    api: tuple[TestClient, Any],
) -> None:
    client, _ = api
    workspace_id = _register(client)
    # video model bound to a text slot → reject at save time (spec §121)
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/model-profiles",
        json={
            "name": "错误方案",
            "bindings": {
                "planning.script": {"model_id": "agnes/agnes-video-v2.0"}
            },
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 422, created.text
    assert created.json()["details"]["code"] == "MODEL_PROFILE_CAPABILITY_MISMATCH"


def test_effective_bindings_and_generation_slot_resolution(
    api: tuple[TestClient, Any],
) -> None:
    client, _ = api
    workspace_id = _register(client)
    project_id = _create_project(client, workspace_id)
    client.post(
        f"/api/v1/workspaces/{workspace_id}/model-profiles",
        json={
            "name": "默认方案",
            "bindings": {"visual.keyframe": {"model_id": "agnes/agnes-image-2.1-flash"}},
            "is_default": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )

    effective = client.get(f"/api/v1/projects/{project_id}/model-bindings/effective")
    assert effective.status_code == 200, effective.text
    keyframe = next(b for b in effective.json() if b["slot"] == "visual.keyframe")
    assert keyframe["model_id"] == "agnes/agnes-image-2.1-flash"
    assert keyframe["source"] == "workspace_profile"

    # standalone image.generate without model_id resolves the visual.keyframe slot
    gen = client.post(
        f"/api/v1/projects/{project_id}/generations",
        json={"capability": "image.generate", "input": {"prompt": "雨夜"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert gen.status_code == 201, gen.text
    assert gen.json()["requested_model"] == "agnes/agnes-image-2.1-flash"


def test_project_profile_snapshot_on_first_write(api: tuple[TestClient, Any]) -> None:
    client, _ = api
    workspace_id = _register(client)
    project_id = _create_project(client, workspace_id)
    client.post(
        f"/api/v1/workspaces/{workspace_id}/model-profiles",
        json={
            "name": "默认方案",
            "bindings": {"planning.script": {"model_id": "litellm/text-llm"}},
            "is_default": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    # First project write snapshots the workspace default (spec §54).
    put = client.put(
        f"/api/v1/projects/{project_id}/model-profile",
        json={"name": "项目方案"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert put.status_code == 200, put.text
    profile = put.json()
    assert profile["project_id"] == project_id
    assert profile["bindings"]["planning.script"]["model_id"] == "litellm/text-llm"

    got = client.get(f"/api/v1/projects/{project_id}/model-profile")
    assert got.status_code == 200, got.text
    assert got.json()["id"] == profile["id"]
