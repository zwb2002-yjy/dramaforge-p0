"""P4-07 New Execution API tests (03 §37)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.main import create_app
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.models import ProviderConnection, ProviderConnectionRevision, ProviderModelBinding
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
            "email": f"wb-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "WB Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _seed_sync(factory: Any, workspace_id: str) -> str:
    """Seed catalog/connection/revision/binding; return the binding id."""

    async def _seed() -> str:
        async with factory() as session:
            from sqlalchemy import select

            from app.access.models import User, Workspace

            workspace = (
                await session.execute(
                    select(Workspace).where(Workspace.id == UUID(workspace_id))
                )
            ).scalar_one_or_none()
            assert workspace is not None
            owner = await session.get(User, workspace.owner_user_id)
            assert owner is not None
            manifest = next(
                item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0"
            )
            entry = ModelCatalogEntry(
                provider_type="agnes",
                protocol_profile="agnes_cn_v1",
                model_id="agnes-video-v2.0",
                model_revision="v1",
                display_name="Agnes Video",
                media_kind="video",
                lifecycle="active",
                catalog_source="official_static",
                capability_manifest_json=manifest,
                option_schema_json={},
                documented_at=date.fromisoformat("2026-08-10"),
                contract_manifest_hash=hash_manifest(manifest),
            )
            session.add(entry)
            await session.flush()
            connection = ProviderConnection(
                workspace_id=workspace.id,
                provider_type="agnes",
                display_name="Agnes",
                base_url="https://api.agnes-ai.cn",
                protocol_profile="agnes_cn_v1",
                credential_id=uuid4(),
                credential_revision=1,
                enabled=True,
                verification_status="verified",
                created_by=owner.id,
                updated_by=owner.id,
            )
            session.add(connection)
            await session.flush()
            revision = ProviderConnectionRevision(
                connection_id=connection.id,
                revision_no=1,
                provider_type="agnes",
                protocol_profile="agnes_cn_v1",
                base_url="https://api.agnes-ai.cn",
                credential_revision_id=connection.credential_id,
            )
            session.add(revision)
            await session.flush()
            binding = ProviderModelBinding(
                workspace_id=workspace.id,
                connection_id=connection.id,
                media_type="video",
                model_id="agnes-video-v2.0",
                purpose="video",
                enabled=True,
                documented=True,
                contract_tested=True,
                account_verified=True,
                quality_gated=True,
                catalog_entry_id=entry.id,
                capability_manifest_hash=entry.contract_manifest_hash,
                remote_resource_kind="model",
                remote_resource_id="agnes-video-v2.0",
                invoke_model_value="agnes-video-v2.0",
                created_by=owner.id,
                updated_by=owner.id,
            )
            session.add(binding)
            await session.flush()
            await session.commit()
            return str(binding.id)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_seed())
    finally:
        loop.close()


def _run(factory: Any, coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _project_id(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/projects",
        headers={CSRF_HEADER: _csrf(client)},
        json={
            "name": "WB Project",
            "aspect_ratio": "9:16",
            "workspace_id": client.headers["X-Workspace-Id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return str(resp.json()["id"])


def _plan_body(binding_id: str) -> dict[str, object]:
    return {
        "stage": "video",
        "prompt": "character walks into frame",
        "semantic_intent": {"intent": "shot_video"},
        "mode_id": "explicit_binding",
        "requested_binding_id": binding_id,
        "accept_approximations": False,
        "references": [],
        "expected_shot_version": None,
    }


def test_execution_plan_preview_returns_frozen_plan(api: tuple[TestClient, Any]) -> None:
    client, factory = api
    _register(client)
    workspace_id = client.headers["X-Workspace-Id"]
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{uuid4()}/execution-plan",
        headers={CSRF_HEADER: _csrf(client)},
        json=_plan_body(binding_id),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["plan_fingerprint"]) == 64
    assert data["plan"]["resolved_model"]["status"] == "RESOLVED"
    # preview never creates a NodeRun
    from app.execution.models import NodeRun

    runs = _run(factory, _count_runs(factory))
    assert runs == 0


async def _count_runs(factory: Any) -> int:
    from sqlalchemy import func, select

    from app.execution.models import NodeRun

    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(NodeRun))).scalar_one()


def test_executions_dispatch_queued_run_and_revalidate_fingerprint(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    _register(client)
    workspace_id = client.headers["X-Workspace-Id"]
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    shot_id = str(uuid4())

    # 1) preview
    preview = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/execution-plan",
        headers={CSRF_HEADER: _csrf(client)},
        json=_plan_body(binding_id),
    ).json()
    fingerprint = preview["plan_fingerprint"]

    # 2) execute with matching fingerprint
    body = {**_plan_body(binding_id), "plan_fingerprint": fingerprint}
    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/executions",
        headers={CSRF_HEADER: _csrf(client), "Idempotency-Key": "test-key-1"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "queued"
    assert data["plan_fingerprint"] == fingerprint

    # 3) mismatched fingerprint is rejected
    bad = {**_plan_body(binding_id), "plan_fingerprint": "0" * 64}
    bad_resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/executions",
        headers={CSRF_HEADER: _csrf(client)},
        json=bad,
    )
    assert bad_resp.status_code == 422

    # 4) idempotency key lands on the NodeRun
    from sqlalchemy import select

    from app.execution.models import NodeRun

    async def _read() -> list[str]:
        async with factory() as session:
            rows = (await session.execute(select(NodeRun.idempotency_key))).scalars().all()
            return list(rows)

    keys = _run(factory, _read())
    assert any("test-key-1" in key for key in keys)
