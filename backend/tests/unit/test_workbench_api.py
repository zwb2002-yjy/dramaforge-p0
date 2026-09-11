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
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
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
        from app.shared.model_registry import load_all_models

        load_all_models()
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
            from app.access.models import User, Workspace
            from sqlalchemy import select

            workspace = (
                await session.execute(select(Workspace).where(Workspace.id == UUID(workspace_id)))
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


def _set_binding_enabled(factory: Any, binding_id: str, *, enabled: bool) -> None:
    async def _update() -> None:
        async with factory() as session:
            binding = await session.get(ProviderModelBinding, UUID(binding_id))
            assert binding is not None
            binding.enabled = enabled
            await session.commit()

    _run(factory, _update())


def _seed_shot_with_formal_keyframe(factory: Any, project_id: str) -> str:
    """Create a Shot + keyframe artifact and mark it formal; return shot id."""

    async def _seed() -> str:
        from uuid import uuid4 as _uuid4

        from app.access.models import Project, User, Workspace
        from app.assets.models import Episode, Scene, Shot
        from app.execution.models import Artifact, NodeRun
        from app.execution.shot_pipeline import (
            SHOT_PIPELINE_TEMPLATE_KEY,
            shot_pipeline_definition,
        )
        from app.production.formal_selection import set_formal_keyframe
        from app.production.service import GraphService

        async with factory() as session:
            project = await session.get(Project, UUID(project_id))
            assert project is not None
            workspace = await session.get(Workspace, project.workspace_id)
            assert workspace is not None
            owner = await session.get(User, workspace.owner_user_id)
            assert owner is not None
            episode = Episode(
                project_id=project.id,
                episode_number=1,
                title="E1",
                synopsis="",
            )
            session.add(episode)
            await session.flush()
            scene = Scene(
                episode_id=episode.id,
                scene_number=1,
                location_name="Studio",
                time_of_day="day",
                synopsis="",
            )
            session.add(scene)
            await session.flush()
            shot = Shot(
                project_id=project.id,
                scene_id=scene.id,
                shot_number=1,
                version=1,
                visual_description="API video shot",
                video_prompt="character walks into frame",
            )
            session.add(shot)
            await session.flush()
            graphs = GraphService(session)
            graph = await graphs.create_graph(
                project_id=project.id,
                scope_type="shot",
                scope_entity_id=shot.id,
                template_key=SHOT_PIPELINE_TEMPLATE_KEY,
                created_by=owner.id,
                definition=shot_pipeline_definition(shot_id=str(shot.id)),
            )
            assert graph.current_version_id is not None
            materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
            version = await graphs.publish(
                version_id=materialized.version.id,
                published_by=owner.id,
            )
            node = materialized.nodes["keyframe"]
            run = NodeRun(
                project_id=project.id,
                graph_version_id=version.id,
                graph_node_id=node.id,
                idempotency_key=f"api-kf:{_uuid4().hex}",
                input_hash="a" * 64,
                status="completed",
                input_snapshot={},
                created_by=owner.id,
            )
            session.add(run)
            await session.flush()
            artifact = Artifact(
                project_id=project.id,
                artifact_type="image",
                storage_state="stored",
                object_key=f"obj/{_uuid4().hex}",
                content_hash="b" * 64,
                mime_type="image/png",
                byte_size=1,
                produced_by_run_id=run.id,
            )
            session.add(artifact)
            await session.flush()
            await set_formal_keyframe(
                session,
                project_id=project.id,
                shot_id=shot.id,
                artifact_id=artifact.id,
            )
            await session.commit()
            return str(shot.id)

    return _run(factory, _seed())


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
        "expected_shot_version": 2,
    }


def test_execution_plan_preview_returns_frozen_plan(api: tuple[TestClient, Any]) -> None:
    client, factory = api
    _register(client)
    workspace_id = client.headers["X-Workspace-Id"]
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    shot_id = _seed_shot_with_formal_keyframe(factory, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/execution-plan",
        headers={CSRF_HEADER: _csrf(client)},
        json=_plan_body(binding_id),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["plan_fingerprint"]) == 64
    assert data["plan"]["resolved_model"]["status"] == "RESOLVED"
    # preview never dispatches a workbench NodeRun
    runs = _run(factory, _count_workbench_runs(factory))
    assert runs == 0


async def _count_workbench_runs(factory: Any) -> int:
    from app.execution.models import NodeRun
    from sqlalchemy import func, select

    async with factory() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(NodeRun)
                .where(NodeRun.idempotency_key.like("workbench:%"))
            )
        ).scalar_one()


def test_executions_dispatch_queued_run_and_revalidate_fingerprint(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    _register(client)
    workspace_id = client.headers["X-Workspace-Id"]
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    shot_id = _seed_shot_with_formal_keyframe(factory, project_id)

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
    from app.execution.models import NodeRun
    from sqlalchemy import select

    async def _read() -> list[str]:
        async with factory() as session:
            rows = (await session.execute(select(NodeRun.idempotency_key))).scalars().all()
            return list(rows)

    keys = _run(factory, _read())
    assert any("test-key-1" in key for key in keys)


def test_execution_rejects_binding_change_after_preview(api: tuple[TestClient, Any]) -> None:
    client, factory = api
    _register(client)
    workspace_id = client.headers["X-Workspace-Id"]
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    shot_id = _seed_shot_with_formal_keyframe(factory, project_id)
    body = _plan_body(binding_id)

    preview_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/execution-plan",
        headers={CSRF_HEADER: _csrf(client)},
        json=body,
    )
    assert preview_response.status_code == 200, preview_response.text
    _set_binding_enabled(factory, binding_id, enabled=False)

    execute_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/executions",
        headers={CSRF_HEADER: _csrf(client)},
        json={
            **body,
            "plan_fingerprint": preview_response.json()["plan_fingerprint"],
            "accepted_approximations": [],
        },
    )
    assert execute_response.status_code == 422
    assert "unavailable" in execute_response.json()["detail"]
    assert _run(factory, _count_workbench_runs(factory)) == 0


def _start_command(api, *, autonomy="AUTO", key="receipt:one"):
    client, factory = api
    workspace_id = _register(client)
    binding_id = _seed_sync(factory, workspace_id)
    project_id = _project_id(client)
    shot_id = _seed_shot_with_formal_keyframe(factory, project_id)
    profile = client.get(f"/api/v1/projects/{project_id}").json()["creative_profile"]
    mode = client.patch(
        f"/api/v1/projects/{project_id}/creative-profile", headers={CSRF_HEADER: _csrf(client)},
        json={"expected_version": profile["version"], "director_autonomy": autonomy},
    )
    assert mode.status_code == 200, mode.text
    path = f"/api/v1/projects/{project_id}/shots/{shot_id}"
    preview = client.post(f"{path}/execution-plan", headers={CSRF_HEADER: _csrf(client)},
                          json=_plan_body(binding_id))
    assert preview.status_code == 200, preview.text
    body = {**_plan_body(binding_id), "plan_fingerprint": preview.json()["plan_fingerprint"]}
    response = client.post(f"{path}/executions",
                           headers={CSRF_HEADER: _csrf(client), "Idempotency-Key": key}, json=body)
    assert response.status_code == 200, response.text
    return project_id, shot_id, binding_id, body, response.json()


def test_lost_execution_response_replays_before_resolution_or_shot_version_checks(api, monkeypatch):
    from app.production.workbench_execution import WorkbenchExecutionService

    client, factory = api
    project_id, shot_id, binding_id, body, receipt = _start_command(api)
    path = f"/api/v1/projects/{project_id}/shots/{shot_id}"
    before = _run(factory, _count_workbench_runs(factory))
    _set_binding_enabled(factory, binding_id, enabled=False)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Receipt replay cannot build a new plan")

    monkeypatch.setattr(WorkbenchExecutionService, "build_plan", forbidden)
    read = client.get(f"{path}/executions/receipt",
                      params={"stage": "video", "idempotency_key": "receipt:one"})
    assert read.status_code == 200 and read.json() == receipt
    replay = client.post(f"{path}/executions", json=body,
                         headers={CSRF_HEADER: _csrf(client), "Idempotency-Key": "receipt:one"})
    assert replay.status_code == 200 and replay.json() == receipt
    assert receipt["director_turn_id"] is None
    changed = client.post(f"{path}/executions", json={**body, "prompt": "changed request"},
                          headers={CSRF_HEADER: _csrf(client), "Idempotency-Key": "receipt:one"})
    assert changed.status_code == 409, changed.text
    assert _run(factory, _count_workbench_runs(factory)) == before
    cross = client.get(f"/api/v1/projects/{uuid4()}/shots/{shot_id}/executions/receipt",
                       params={"stage": "video", "idempotency_key": "receipt:one"})
    assert cross.status_code in {403, 404}


@pytest.mark.parametrize("autonomy,expected", [("AUTO", "open_editing"),
                                               ("ASSIST", "review_saved_design")])
def test_actual_command_worker_and_formal_api_reach_next_checkpoint(
    api, monkeypatch, autonomy, expected,
):
    from app.execution.models import Artifact, NodeRun, ProviderOperation
    from app.workers import jobs
    from sqlalchemy import func, select

    client, factory = api
    project_id, shot_id, _binding, _body, receipt = _start_command(api, autonomy=autonomy)
    assert receipt["director_turn_id"] is None
    turn_id = _run(factory, _deliver_production_notices(factory, project_id))
    assert turn_id is not None
    monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
    first_scan = _run(factory, jobs.reconcile_waiting_director_turns({}))
    assert first_scan["unchanged"] == 1
    count = _run(factory, _count_workbench_runs(factory))

    async def finish():
        async with factory() as session:
            run = await session.get(NodeRun, UUID(receipt["node_run_id"]))
            artifact = Artifact(project_id=UUID(project_id), artifact_type="video",
                                storage_state="available", object_key=f"obj/{uuid4().hex}",
                                content_hash="e" * 64, mime_type="video/mp4", byte_size=1,
                                produced_by_run_id=run.id)
            session.add(artifact)
            await session.flush()
            run.status = "completed"
            run.result_artifact_id = artifact.id
            await session.commit()
            return str(artifact.id)

    artifact_id = _run(factory, finish())
    assert _run(factory, jobs.reconcile_waiting_director_turns({}))["reconciled"] == 1
    selected = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/formal-video",
                           headers={CSRF_HEADER: _csrf(client)},
                           json={"artifact_id": artifact_id, "expected_shot_version": 2})
    assert selected.status_code == 200, selected.text
    _run(factory, _deliver_production_notices(factory, project_id))
    turn = client.get(f"/api/v1/projects/{project_id}/director/turns/{turn_id}")
    assert turn.status_code == 200, turn.text
    state = turn.json()
    assert state["status"] == "completed" and state["step_count"] == 4
    action = state["response_summary"]["coordination"]["current_action"]
    assert action["action"] == expected and action["requires_confirmation"]
    assert action["shot_version"] == 3
    assert _run(factory, _count_workbench_runs(factory)) == count

    async def operations():
        async with factory() as session:
            return await session.scalar(select(func.count()).select_from(ProviderOperation))

    assert _run(factory, operations()) == 0


def test_manual_command_keeps_production_available_without_proactive_followup(api):
    _project, _shot, _binding, _body, receipt = _start_command(api, autonomy="MANUAL")
    assert receipt["status"] == "queued"
    assert receipt["director_turn_id"] is None


@pytest.mark.parametrize("autonomy", ["AUTO", "ASSIST", "MANUAL"])
def test_production_acceptance_never_enters_director_when_director_is_broken(
    api, monkeypatch, autonomy,
):
    from app.director.business_checkpoints import DirectorBusinessCheckpoints

    def unavailable(*args, **kwargs):
        raise RuntimeError("Director unavailable")

    monkeypatch.setattr(DirectorBusinessCheckpoints, "__init__", unavailable)
    _project, _shot, _binding, _body, receipt = _start_command(api, autonomy=autonomy)
    assert receipt["status"] == "queued" and receipt["director_turn_id"] is None


async def _deliver_production_notices(factory, project_id):
    """Separate test transactions emulate delivery; real Redis/PG tests cover transport."""
    from app.director.inbox import receive_production_event
    from app.director.turn_models import DirectorTurn
    from app.director.wakeup import apply_director_wakeup
    from app.events.models import OutboxEvent
    from sqlalchemy import select

    async with factory() as session:
        ids = list((await session.scalars(select(OutboxEvent.event_id).where(
            OutboxEvent.project_id == UUID(project_id), OutboxEvent.topic == "production.facts.v1",
        ))).all())
    for event_id in ids:
        async with factory() as session:
            inbox_id = await receive_production_event(
                session, project_id=UUID(project_id), event_id=event_id,
            )
            await session.commit()
        async with factory() as session:
            await apply_director_wakeup(session, inbox_id=inbox_id)
            await session.commit()
    async with factory() as session:
        return await session.scalar(select(DirectorTurn.id).where(
            DirectorTurn.project_id == UUID(project_id),
        ))
