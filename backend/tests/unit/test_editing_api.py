"""P9-03A project-scoped EditingAdapter HTTP lifecycle tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Asset, AssetVersion, Episode, Scene, Shot
from app.config import clear_settings_cache, get_settings
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.main import create_app
from app.production.models import GraphVersion, ProductionGraph
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
def api() -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    clear_settings_cache()
    from sqlalchemy.pool import StaticPool

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


def _run(factory: async_sessionmaker[AsyncSession], coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"editing-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Editing Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _create_project(client: TestClient, *, name: str) -> str:
    response = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": client.headers["X-Workspace-Id"],
            "name": name,
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _seed_formal_facts(
    factory: async_sessionmaker[AsyncSession], project_id: str
) -> None:
    async with factory() as session:
        project = await session.get(Project, UUID(project_id))
        assert project is not None
        workspace = await session.get(Workspace, project.workspace_id)
        assert workspace is not None
        user = await session.get(User, workspace.owner_user_id)
        assert user is not None

        episode = Episode(project_id=project.id, episode_number=1, title="Episode 1", synopsis="")
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id,
            scene_number=1,
            location_name="Studio",
            time_of_day="day",
            synopsis="Editing API scene",
        )
        session.add(scene)
        await session.flush()

        asset = Asset(
            project_id=project.id,
            kind="character",
            name="Lead",
            description="Lead asset",
            status="active",
            metadata_json={"role": "lead"},
            version=1,
        )
        session.add(asset)
        await session.flush()
        asset_version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=1,
            kind="character",
            name="Lead",
            description="Lead asset",
            metadata_json={"role": "lead"},
            status="formal",
            created_by=user.id,
        )
        session.add(asset_version)
        await session.flush()
        asset.current_version_id = asset_version.id

        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=1,
            shot_type="medium",
            camera_move="static",
            visual_description="Lead looks toward camera",
            dialogue="Hello",
            duration_seconds=Decimal("2.500"),
            status="completed",
            sort_order=1,
            version=4,
            image_prompt="formal image prompt",
            video_prompt="formal video prompt",
        )
        session.add(shot)
        await session.flush()

        graph = await GraphService(session).create_graph(
            project_id=project.id,
            scope_type="shot",
            scope_entity_id=shot.id,
            template_key="editing-api-test",
            created_by=user.id,
            definition={"nodes": ["video"], "edges": []},
        )
        assert graph.current_version_id is not None
        materialized = await GraphService(session).materialize_definition(
            version_id=graph.current_version_id
        )
        node = materialized.nodes["video"]
        run = NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=node.id,
            idempotency_key=f"editing-api:{uuid4().hex}",
            input_hash="a" * 64,
            status="completed",
            input_snapshot={"shot_id": str(shot.id), "stage": "video"},
            output_summary={"source": "editing-api-test"},
            result_artifact_id=None,
            created_by=user.id,
        )
        session.add(run)
        await session.flush()
        artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="stored",
            object_key=f"editing-api/{uuid4().hex}.mp4",
            content_hash="b" * 64,
            mime_type="video/mp4",
            byte_size=10,
            duration_seconds=Decimal("2.500"),
            produced_by_run_id=run.id,
        )
        session.add(artifact)
        await session.flush()
        run.result_artifact_id = artifact.id
        shot.formal_video_artifact_id = artifact.id
        operation = ProviderOperation(
            node_run_id=run.id,
            attempt_no=1,
            purpose="primary",
            operation_kind="video.generate",
            actual_provider="fake",
            actual_model="fake-video",
            request_fingerprint="c" * 64,
            status="succeeded",
            request_summary={"test": True},
            response_summary={"test": True},
            token_usage={},
            submitted_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(operation)
        await session.commit()


async def _formal_snapshot(
    factory: async_sessionmaker[AsyncSession], project_id: str
) -> dict[str, object]:
    async with factory() as session:
        shot = (
            await session.execute(select(Shot).where(Shot.project_id == UUID(project_id)))
        ).scalar_one()
        asset = (
            await session.execute(select(Asset).where(Asset.project_id == UUID(project_id)))
        ).scalar_one()
        graph = (
            await session.execute(
                select(ProductionGraph).where(ProductionGraph.project_id == UUID(project_id))
            )
        ).scalar_one()
        graph_version = (
            await session.execute(
                select(GraphVersion).where(GraphVersion.graph_id == graph.id)
            )
        ).scalar_one()
        run = (
            await session.execute(select(NodeRun).where(NodeRun.project_id == UUID(project_id)))
        ).scalar_one()
        operation = (
            await session.execute(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
            )
        ).scalar_one()
        return {
            "shot": (
                shot.id,
                shot.version,
                shot.image_prompt,
                shot.video_prompt,
                dict(shot.director_state),
                shot.formal_video_artifact_id,
            ),
            "asset": (asset.id, asset.version, asset.current_version_id, asset.status),
            "graph": (graph.id, graph.version, graph.current_version_id, graph.status),
            "graph_version": (
                graph_version.id,
                graph_version.definition_hash,
                dict(graph_version.definition),
            ),
            "run": (
                run.id,
                run.status,
                run.input_hash,
                dict(run.input_snapshot),
                run.result_artifact_id,
            ),
            "operation": (
                operation.id,
                operation.status,
                operation.actual_provider,
                operation.actual_model,
                operation.request_fingerprint,
            ),
        }


def test_editing_http_lifecycle_preserves_formal_facts(
    api: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = api
    _register(client)
    project_id = _create_project(client, name="Editing API Project")
    _run(factory, _seed_formal_facts(factory, project_id))
    before = _run(factory, _formal_snapshot(factory, project_id))

    created = client.post(
        f"/api/v1/projects/{project_id}/edit-sessions",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    session_id = created_body["id"]
    assert created_body["name"] == "Long-form Edit"
    assert created_body["timeline"]["clips"][0]["artifact_id"]
    assert created_body["production_lineage"]["lineage_readonly"] is True

    loaded = client.get(f"/api/v1/projects/{project_id}/edit-sessions/{session_id}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["timeline"] == created_body["timeline"]

    edited_timeline = {
        "clips": [{**created_body["timeline"]["clips"][0], "duration_seconds": 1.25}],
        "metadata": {"edited": True, "notes": "manual trim"},
    }
    saved = client.patch(
        f"/api/v1/projects/{project_id}/edit-sessions/{session_id}/timeline",
        json={"timeline": edited_timeline},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["timeline"] == edited_timeline
    assert saved.json()["production_lineage"] == created_body["production_lineage"]

    reopened = client.get(f"/api/v1/projects/{project_id}/edit-sessions/{session_id}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["timeline"] == edited_timeline

    exported = client.get(
        f"/api/v1/projects/{project_id}/edit-sessions/{session_id}/export"
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["session_id"] == session_id
    assert exported.json()["clip_count"] == 1
    assert exported.json()["duration_seconds"] == 1.25
    assert exported.json()["production_lineage"] == created_body["production_lineage"]
    assert _run(factory, _formal_snapshot(factory, project_id)) == before


def test_editing_http_rejects_lineage_and_missing_csrf(
    api: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = api
    _register(client)
    project_id = _create_project(client, name="Editing Validation Project")
    _run(factory, _seed_formal_facts(factory, project_id))
    created = client.post(
        f"/api/v1/projects/{project_id}/edit-sessions",
        json={"name": "Validation Edit"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    no_csrf = client.patch(
        f"/api/v1/projects/{project_id}/edit-sessions/{session_id}/timeline",
        json={"timeline": {"clips": [], "metadata": {}}},
    )
    assert no_csrf.status_code == 403, no_csrf.text

    top_level_lineage = client.patch(
        f"/api/v1/projects/{project_id}/edit-sessions/{session_id}/timeline",
        json={
            "timeline": {"clips": [], "metadata": {}},
            "production_lineage": {"tamper": True},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert top_level_lineage.status_code == 422, top_level_lineage.text

    nested_lineage = client.patch(
        f"/api/v1/projects/{project_id}/edit-sessions/{session_id}/timeline",
        json={
            "timeline": {
                "clips": [],
                "metadata": {},
                "production_lineage": {"tamper": True},
            }
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert nested_lineage.status_code == 422, nested_lineage.text
    loaded = client.get(f"/api/v1/projects/{project_id}/edit-sessions/{session_id}")
    assert loaded.json()["timeline"]["clips"]


def test_editing_http_is_project_scoped(
    api: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _factory = api
    _register(client)
    project_a = _create_project(client, name="Editing Project A")
    project_b = _create_project(client, name="Editing Project B")
    created_a = client.post(
        f"/api/v1/projects/{project_a}/edit-sessions",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    created_b = client.post(
        f"/api/v1/projects/{project_b}/edit-sessions",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created_a.status_code == 201, created_a.text
    assert created_b.status_code == 201, created_b.text
    session_a = created_a.json()["id"]
    session_b = created_b.json()["id"]

    foreign_get = client.get(f"/api/v1/projects/{project_a}/edit-sessions/{session_b}")
    assert foreign_get.status_code == 404, foreign_get.text
    reverse_get = client.get(f"/api/v1/projects/{project_b}/edit-sessions/{session_a}")
    assert reverse_get.status_code == 404, reverse_get.text
    unknown_get = client.get(f"/api/v1/projects/{project_a}/edit-sessions/{uuid4()}")
    assert unknown_get.status_code == 404, unknown_get.text
