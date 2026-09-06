"""Model candidates API: read-only, reuses the shared eligibility engine."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.main import create_app
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
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


def _seed_catalog(factory: Any) -> None:
    manifest = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0")

    async def _insert() -> None:
        async with factory() as session:
            session.add(
                ModelCatalogEntry(
                    provider_type=manifest["provider_type"],
                    protocol_profile=manifest["protocol_profile"],
                    model_id=manifest["model_id"],
                    model_revision=manifest["model_revision"],
                    display_name=manifest["display_name"],
                    media_kind=manifest["media_kind"],
                    lifecycle="active",
                    catalog_source="official_static",
                    capability_manifest_json=manifest,
                    option_schema_json=manifest.get("option_schema") or {},
                    documented_at=date.fromisoformat(manifest["documented_at"]),
                    contract_manifest_hash=hash_manifest(manifest),
                )
            )
            await session.commit()

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_insert())
    finally:
        loop.close()


def test_model_candidates_api_lists_unverified_binding_as_ineligible(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    keyring_key = Fernet.generate_key().decode("ascii")
    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"candidates-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Candidate Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    _seed_catalog(factory)

    # BYOK keys for credential encryption.
    import os

    os.environ["BYOK_PRIMARY_KEY_VERSION"] = "v1"
    os.environ["BYOK_KEYRING"] = f"v1:{keyring_key}"
    clear_settings_cache()

    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections",
        json={
            "provider_type": "agnes",
            "protocol_profile": "agnes_cn_v1",
            "api_key": "agnes-secret",
            "enabled": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]

    binding = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings",
        json={
            "media_type": "video",
            "model_id": "agnes-video-v2.0",
            "purpose": "video",
            "enabled": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert binding.status_code == 201, binding.text
    assert binding.json()["invoke_model_value"] == "agnes-video-v2.0"
    assert binding.json()["account_verified"] is False

    project = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"candidates-{uuid4().hex[:8]}",
            "aspect_ratio": "9:16",
            "budget_limit": "0",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    response = client.get(
        f"/api/v1/projects/{project_id}/model-candidates?operation=video.generate"
    )
    assert response.status_code == 200, response.text
    candidates = response.json()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["model_id"] == "agnes-video-v2.0"
    assert candidate["purpose"] == "video"
    assert candidate["eligible"] is False
    codes = {issue["code"] for issue in candidate["issues"]}
    assert "MODEL_NOT_ACCOUNT_VERIFIED" in codes
    assert "MODEL_QUALITY_GATE_MISSING" in codes


def test_model_candidates_api_requires_project_ownership(api: tuple[TestClient, Any]) -> None:
    client, _factory = api
    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"candidates-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Candidate Owner",
        },
    )
    other_workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = other_workspace_id
    # A project id from another workspace must 404 under this workspace header.
    response = client.get(
        f"/api/v1/projects/{uuid4()}/model-candidates?operation=image.generate"
    )
    assert response.status_code in {400, 404}
