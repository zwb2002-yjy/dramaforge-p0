"""V3 Unified Generation API tests (Phase 6, spec §58/§44)."""

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
            "email": f"gen-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Gen Owner",
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
            "name": "GenProject",
            "aspect_ratio": "9:16",
            "budget_limit": "50.00",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    return str(project.json()["id"])


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

    def test_litellm_models_use_gateway_configuration(
        self, api: tuple[TestClient, Any]
    ) -> None:
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
            response = client.get(
                "/api/v1/models", params={"capability": "text.generate"}
            )
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


class TestGenerationCreate:
    def test_unsupported_capability_rejected(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        workspace_id = _register(client)
        project_id = _create_project(client, workspace_id)
        response = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={
                "capability": "video.image_to_video",
                "input": {"prompt": "p"},
            },
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_missing_prompt_rejected(self, api: tuple[TestClient, Any]) -> None:
        client, _ = api
        workspace_id = _register(client)
        project_id = _create_project(client, workspace_id)
        response = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={
                "capability": "image.generate",
                "input": {},
            },
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 422

    def test_create_image_generation_and_read(
        self, api: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = api
        workspace_id = _register(client)
        project_id = _create_project(client, workspace_id)

        async def fake_enqueue(self: object, node_run_id: Any) -> str:
            return f"fake-{node_run_id}"

        monkeypatch.setattr(
            "app.providers.generation_service.AgentRunScheduler.enqueue_node_run_only",
            fake_enqueue,
        )
        response = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={
                "capability": "image.generate",
                "input": {"prompt": "一片静谧的竹林"},
            },
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["requested_capability"] == "image.generate"
        operation_id = body["operation_id"]

        read = client.get(f"/api/v1/projects/{project_id}/generations/{operation_id}")
        assert read.status_code == 200
        assert read.json()["status"] == "queued"

    def test_idempotency_key_returns_same_operation(
        self, api: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = api
        workspace_id = _register(client)
        project_id = _create_project(client, workspace_id)
        key = f"idem-{uuid4().hex}"

        async def fake_enqueue(self: object, node_run_id: Any) -> str:
            return f"fake-{node_run_id}"

        monkeypatch.setattr(
            "app.providers.generation_service.AgentRunScheduler.enqueue_node_run_only",
            fake_enqueue,
        )
        headers = {CSRF_HEADER: _csrf(client), "Idempotency-Key": key}
        first = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={"capability": "image.generate", "input": {"prompt": "p"}},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        second = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={"capability": "image.generate", "input": {"prompt": "p"}},
            headers=headers,
        )
        assert second.status_code == 201, second.text
        assert first.json()["operation_id"] == second.json()["operation_id"]

    def test_same_key_different_request_conflicts(
        self, api: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BLOCK-1: same Idempotency-Key + different input is a 409
        IDEMPOTENCY_KEY_REUSED, never a silent reuse of the first operation."""
        client, _ = api
        workspace_id = _register(client)
        project_id = _create_project(client, workspace_id)
        key = f"idem-{uuid4().hex}"

        async def fake_enqueue(self: object, node_run_id: Any) -> str:
            return f"fake-{node_run_id}"

        monkeypatch.setattr(
            "app.providers.generation_service.AgentRunScheduler.enqueue_node_run_only",
            fake_enqueue,
        )
        headers = {CSRF_HEADER: _csrf(client), "Idempotency-Key": key}
        first = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={"capability": "image.generate", "input": {"prompt": "女孩走路"}},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        second = client.post(
            f"/api/v1/projects/{project_id}/generations",
            json={"capability": "image.generate", "input": {"prompt": "汽车行驶"}},
            headers=headers,
        )
        assert second.status_code == 409, second.text
        assert second.json()["details"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        # the second request must not have created a second operation: the 409
        # is the error body, not a generation response
        assert "operation_id" not in second.json()
        assert second.json()["detail"] is not None
