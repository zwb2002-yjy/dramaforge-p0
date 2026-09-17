"""V3 Generation read-surface tests (spec §58).

Media generation has one product writer (workbench execution), so this file
only covers the read-only catalog: capabilities, models and model manifests.
The GenerationService domain behaviour stays covered by
tests/unit/test_v3_review_fixes.py, test_model_profile_snapshot.py and
tests/integration/test_runtime_recovery_matrix_pg.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from app.api.deps import settings_dep
from app.config import clear_settings_cache, get_settings
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
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


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _register(client: TestClient) -> str:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"gen-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Gen Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


class TestReadSurface:
    def test_list_capabilities(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        _register(client)
        response = client.get("/api/v1/capabilities")
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()}
        assert "image.generate" in ids
        assert "video.image_to_video" in ids
        assert "audio.tts" in ids

    def test_list_models_by_capability(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        _register(client)
        response = client.get("/api/v1/models", params={"capability": "image.generate"})
        assert response.status_code == 200
        models = response.json()
        assert len(models) == 3
        ids = {item["id"] for item in models}
        assert "agnes/agnes-image-2.1-flash" in ids
        assert "volcengine/doubao-seedream-4-0-250828" in ids
        assert "minimax/image-01" in ids
        assert all(item["provider_id"] in {"agnes", "minimax", "volcengine"} for item in models)

    def test_litellm_models_use_gateway_configuration(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        _register(client)
        gateway_settings = get_settings().model_copy(
            update={
                "litellm_gateway_url": "http://litellm.test",
                "litellm_api_key": "gateway-key",
            }
        )
        client.app.dependency_overrides[settings_dep] = lambda: gateway_settings
        try:
            response = client.get("/api/v1/models", params={"capability": "text.generate"})
        finally:
            client.app.dependency_overrides.pop(settings_dep, None)
        assert response.status_code == 200, response.text
        models = response.json()
        litellm = [item for item in models if item["provider_id"] == "litellm"]
        assert litellm
        assert all(item["configured"] and item["available"] for item in litellm)

    def test_get_model_manifest(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        _register(client)
        response = client.get("/api/v1/models/agnes/agnes-video-v2.0")
        assert response.status_code == 200
        manifest = response.json()
        assert manifest["id"] == "agnes/agnes-video-v2.0"
        assert manifest["execution_mode"] == "async_poll"
        assert "video.image_to_video" in manifest["capability_specs"]

    def test_unknown_capability_rejected(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        _register(client)
        response = client.get("/api/v1/models", params={"capability": "nope.nope"})
        assert response.status_code == 422
