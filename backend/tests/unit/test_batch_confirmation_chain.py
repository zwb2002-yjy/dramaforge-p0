"""Real-session batch confirmation-chain tests (backend-review N-01 regression).

The mocked tests in ``test_backend_review_regressions.py`` pin the replay and
fingerprint-binding logic. These tests instead run the real chain end-to-end on
SQLite through the actual HTTP surface, the real resolver and the real
Compiler: preview must bind per-shot Compiler proofs into the preview
fingerprint, dispatch must pass the shared confirmation gate, and no path may
create a ProviderOperation (there is no Provider call in this suite).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tests.unit.model_infra_fixture import seed_model_infra


@pytest.fixture()
def batch_api() -> Iterator[tuple[TestClient, Any]]:
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
    from uuid import uuid4

    client.post(
        "/api/v1/auth/register",
        json={
            "email": f"batch-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Batch Owner",
        },
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _seed_project(
    client: TestClient, factory: Any, workspace_id: str, *, shots: int = 1
) -> tuple[str, str]:
    """Create a project with image-prompt shots; return (project_id, first shot_id)."""

    project_id = str(
        client.post(
            "/api/v1/projects",
            headers={CSRF_HEADER: _csrf(client)},
            json={
                "name": "Batch Project",
                "aspect_ratio": "9:16",
                "workspace_id": workspace_id,
            },
        ).json()["id"]
    )

    async def _seed() -> list[str]:
        from app.access.models import Project, User
        from app.assets.models import Episode, Scene, Shot

        async with factory() as session:
            project = await session.get(Project, UUID(project_id))
            assert project is not None
            owner = (
                await session.execute(select(User).order_by(User.created_at.desc()).limit(1))
            ).scalar_one()
            await seed_model_infra(session, project=project, user=owner)
            episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
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
            shot_ids: list[str] = []
            for index in range(shots):
                shot = Shot(
                    project_id=project.id,
                    scene_id=scene.id,
                    shot_number=index + 1,
                    version=1,
                    visual_description="A batch image shot",
                    image_prompt="character walks into frame",
                )
                session.add(shot)
                await session.flush()
                shot_ids.append(str(shot.id))
            await session.commit()
            return shot_ids

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        ids = loop.run_until_complete(_seed())
    finally:
        loop.close()
    return project_id, ids[0]


def _batch_dispatch_body(preview: dict[str, Any], *, batch_key: str = "bk-1") -> dict[str, Any]:
    return {
        "stage": preview["stage"],
        "scene_id": preview.get("scene_id"),
        "preview_fingerprint": preview["fingerprint"],
        "batch_key": batch_key,
        "max_provider_calls": preview["ready_count"],
        "owner_authorized": True,
    }


def test_batch_confirmation_chain_end_to_end(
    batch_api: tuple[TestClient, Any],
) -> None:
    client, factory = batch_api
    _register(client)
    workspace_id = str(client.headers["X-Workspace-Id"])
    project_id, shot_id = _seed_project(client, factory, workspace_id)

    # 1) Preview classifies the shot as ready with a per-shot plan fingerprint.
    preview = client.get(
        f"/api/v1/projects/{project_id}/batch-production/preview",
        params={"stage": "image_keyframe"},
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["ready_count"] == 1
    assert data["items"][0]["disposition"] == "ready"
    assert data["items"][0]["shot_id"] == shot_id
    assert data["items"][0]["plan_fingerprint"] is not None
    assert len(data["fingerprint"]) == 64

    # 2) Dispatch passes the shared Compiler confirmation gate and creates runs.
    dispatch = client.post(
        f"/api/v1/projects/{project_id}/batch-production",
        headers={CSRF_HEADER: _csrf(client)},
        json=_batch_dispatch_body(data),
    )
    assert dispatch.status_code == 200, dispatch.text
    receipt = dispatch.json()
    assert receipt["accepted_count"] == 1
    assert receipt["statuses"] == ["queued"]

    from app.execution.models import NodeRun, ProviderOperation

    async def _inspect() -> dict[str, Any]:
        async with factory() as session:
            runs = list((await session.scalars(select(NodeRun))).all())
            ops = list((await session.scalars(select(ProviderOperation))).all())
            return {
                "batch_runs": [run for run in runs if "batch:" in (run.idempotency_key or "")],
                "other_runs": [run for run in runs if "batch:" not in (run.idempotency_key or "")],
                "ops": ops,
            }

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        state = loop.run_until_complete(_inspect())
    finally:
        loop.close()
    # Exactly one batch media run; the remaining runs are the pure upstream
    # runs the canonical shot pipeline requires (zero-provider, queued).
    assert len(state["batch_runs"]) == 1
    run = state["batch_runs"][0]
    assert run.id == UUID(receipt["node_run_ids"][0])
    assert state["other_runs"]
    assert all(run_.status == "queued" for run_ in state["other_runs"])
    assert run.id == UUID(receipt["node_run_ids"][0])
    # The frozen plan snapshot carries the confirmed Compiler proof.
    snapshot = run.input_snapshot or {}
    assert snapshot["confirmed_compiler_wire_fingerprint"] is not None
    assert len(snapshot["confirmed_compiler_wire_fingerprint"]) == 64
    # Batch authorization is frozen exactly once with the proof binding.
    authorization = snapshot["paid_authorization"]
    assert authorization["batch_key"] == "bk-1"
    assert authorization["preview_fingerprint"] == data["fingerprint"]
    assert authorization["call_index"] == 1
    assert authorization["authorized_call_count"] == 1
    # No ProviderOperation exists: this chain never performs a Provider call.
    assert state["ops"] == []

    # 3) Replaying the same batch_key returns the same frozen receipts.
    replay = client.post(
        f"/api/v1/projects/{project_id}/batch-production",
        headers={CSRF_HEADER: _csrf(client)},
        json=_batch_dispatch_body(data),
    )
    assert replay.status_code == 200, replay.text
    replayed = replay.json()
    assert replayed["node_run_ids"] == receipt["node_run_ids"]

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        state_after_replay = loop.run_until_complete(_inspect())
    finally:
        loop.close()
    assert len(state_after_replay["batch_runs"]) == 1
    assert state_after_replay["ops"] == []


def test_batch_dispatch_rejects_missing_compiler_proof(
    batch_api: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Compiler-unready model makes the shot blocked, not silently dispatched."""

    client, factory = batch_api
    _register(client)
    workspace_id = str(client.headers["X-Workspace-Id"])
    project_id, _shot_id = _seed_project(client, factory, workspace_id)

    from app.production.workbench_execution import WorkbenchExecutionService

    async def _unavailable_compiler(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        WorkbenchExecutionService, "preview_compiler_contract", _unavailable_compiler
    )

    preview = client.get(
        f"/api/v1/projects/{project_id}/batch-production/preview",
        params={"stage": "image_keyframe"},
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["ready_count"] == 0
    assert data["blocked_count"] == 1
    assert data["items"][0]["disposition"] == "blocked"
    assert data["items"][0]["reason"] == "COMPILER_WIRE_CONFIRMATION_REQUIRED"


def test_batch_dispatch_rejects_forged_max_provider_calls(
    batch_api: tuple[TestClient, Any],
) -> None:
    """A lowered operation ceiling is rejected instead of trimming the batch."""

    client, factory = batch_api
    _register(client)
    workspace_id = str(client.headers["X-Workspace-Id"])
    project_id, _shot_id = _seed_project(client, factory, workspace_id, shots=2)

    preview = client.get(
        f"/api/v1/projects/{project_id}/batch-production/preview",
        params={"stage": "image_keyframe"},
    ).json()
    assert preview["ready_count"] == 2

    body = _batch_dispatch_body(preview)
    body["max_provider_calls"] = 1
    dispatch = client.post(
        f"/api/v1/projects/{project_id}/batch-production",
        headers={CSRF_HEADER: _csrf(client)},
        json=body,
    )
    assert dispatch.status_code == 422, dispatch.text
    assert dispatch.json()["details"]["code"] == "BATCH_CALL_LIMIT_EXCEEDED"

    async def _runs() -> list[Any]:
        from app.execution.models import NodeRun

        async with factory() as session:
            return [
                run
                for run in (await session.scalars(select(NodeRun))).all()
                if "batch:" in (run.idempotency_key or "")
            ]

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        runs = loop.run_until_complete(_runs())
    finally:
        loop.close()
    assert runs == []


def test_batch_dispatch_requires_authentication(
    batch_api: tuple[TestClient, Any],
) -> None:
    """Unauthenticated dispatch is rejected before any preview work."""

    client, _factory = batch_api
    dispatch = client.post(
        f"/api/v1/projects/{uuid4()}/batch-production",
        headers={CSRF_HEADER: _csrf(client)},
        json={
            "stage": "image_keyframe",
            "scene_id": None,
            "preview_fingerprint": "a" * 64,
            "batch_key": "bk",
            "max_provider_calls": 1,
            "owner_authorized": True,
        },
    )
    assert dispatch.status_code == 401


def test_batch_preview_recomputes_after_shot_change(
    batch_api: tuple[TestClient, Any],
) -> None:
    """A prompt edit invalidates the old preview fingerprint (stale gate)."""

    client, factory = batch_api
    _register(client)
    workspace_id = str(client.headers["X-Workspace-Id"])
    project_id, shot_id = _seed_project(client, factory, workspace_id)

    first = client.get(
        f"/api/v1/projects/{project_id}/batch-production/preview",
        params={"stage": "image_keyframe"},
    ).json()

    async def _edit_prompt() -> None:
        from app.assets.models import Shot

        async with factory() as session:
            shot = await session.get(Shot, UUID(shot_id))
            assert shot is not None
            shot.image_prompt = "edited prompt for stale preview"
            await session.commit()

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_edit_prompt())
    finally:
        loop.close()

    second = client.get(
        f"/api/v1/projects/{project_id}/batch-production/preview",
        params={"stage": "image_keyframe"},
    ).json()
    assert second["ready_count"] == 1
    assert second["fingerprint"] != first["fingerprint"]

    stale = client.post(
        f"/api/v1/projects/{project_id}/batch-production",
        headers={CSRF_HEADER: _csrf(client)},
        json=_batch_dispatch_body(first),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["details"]["code"] == "BATCH_PREVIEW_STALE"


def test_batch_fill_skips_candidates_formal_and_active_shots(batch_api) -> None:
    """V4: fill creates only missing candidates and never bypasses review."""
    from app.access.models import Project, User
    from app.assets.models import Shot
    from app.execution.models import NodeRun, ProviderOperation
    from tests.unit.test_formal_selection import _make_keyframe_artifact

    client, factory = batch_api
    workspace_id = _register(client)
    project_id, _ = _seed_project(client, factory, workspace_id, shots=4)
    path = f"/api/v1/projects/{project_id}/batch-production"
    before = client.get(f"{path}/preview", params={"stage": "image_keyframe"}).json()
    assert before["ready_count"] == 4

    async def seed_states():
        async with factory() as session:
            project = await session.get(Project, UUID(project_id))
            owner = await session.scalar(select(User))
            shots = list((await session.scalars(select(Shot).order_by(Shot.shot_number))).all())
            for index in range(3):
                artifact = await _make_keyframe_artifact(
                    session,
                    project=project,
                    shot_id=shots[index].id,
                    user=owner,
                    run_status="running" if index == 2 else "completed",
                )
                if index == 1:
                    shots[index].formal_keyframe_artifact_id = artifact.id
                if index == 2:
                    run = await session.get(NodeRun, artifact.produced_by_run_id)
                    run.input_snapshot = {**run.input_snapshot, "node_key": "keyframe"}
            await session.commit()
            return [str(shot.id) for shot in shots]

    shot_ids = asyncio.run(seed_states())
    preview_response = client.get(f"{path}/preview", params={"stage": "image_keyframe"})
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert (preview["ready_count"], preview["skipped_count"], preview["blocked_count"]) == (1, 3, 0)
    items = {item["shot_id"]: item for item in preview["items"]}
    assert items[shot_ids[0]]["reason"] == "CANDIDATE_AWAITING_REVIEW"
    assert items[shot_ids[1]]["reason"] == "ALREADY_FORMAL"
    assert items[shot_ids[2]]["reason"] == "STAGE_ALREADY_ACTIVE"
    assert items[shot_ids[3]]["disposition"] == "ready"
    todos = client.get(f"/api/v1/projects/{project_id}/production-todos").json()
    assert todos["counts"]["awaiting_review"] == 1
    assert todos["counts"]["generating"] == 1
    stale = client.post(
        path, headers={CSRF_HEADER: _csrf(client)}, json=_batch_dispatch_body(before)
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["details"]["code"] == "BATCH_PREVIEW_STALE"
    dispatched = client.post(
        path, headers={CSRF_HEADER: _csrf(client)}, json=_batch_dispatch_body(preview)
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["accepted_count"] == 1

    async def assert_no_paid_operations():
        async with factory() as session:
            assert list((await session.scalars(select(ProviderOperation))).all()) == []
            runs = list((await session.scalars(select(NodeRun))).all())
            batch_runs = [run for run in runs if run.input_snapshot.get("paid_authorization")]
            assert len(batch_runs) == 1
            assert batch_runs[0].input_snapshot["shot_id"] == shot_ids[3]

    asyncio.run(assert_no_paid_operations())


@pytest.mark.parametrize("with_pending", [False, True])
def test_batch_fill_reports_rejected_candidates_honestly(batch_api, with_pending) -> None:
    """A human-rejected candidate stays skipped (fill never re-pays), but the
    reason must state the rejection instead of claiming review is pending."""
    from datetime import UTC, datetime, timedelta

    from app.access.models import Project, User
    from app.assets.models import Shot
    from app.execution.models import GraphNode, NodeRun
    from app.production.models import ProductionGraph
    from app.production.review_gate import record_human_decision
    from tests.unit.test_formal_selection import _make_keyframe_artifact

    client, factory = batch_api
    workspace_id = _register(client)
    project_id, _ = _seed_project(client, factory, workspace_id, shots=2)
    path = f"/api/v1/projects/{project_id}/batch-production"
    before = client.get(f"{path}/preview", params={"stage": "image_keyframe"}).json()
    assert before["ready_count"] == 2

    async def seed_rejected_candidate():
        async with factory() as session:
            project = await session.get(Project, UUID(project_id))
            owner = await session.scalar(select(User))
            shots = list((await session.scalars(select(Shot).order_by(Shot.shot_number))).all())
            pending = (
                await _make_keyframe_artifact(
                    session, project=project, shot_id=shots[0].id, user=owner, attempt_no=1
                )
                if with_pending
                else None
            )
            if pending is not None:
                pending.created_at = datetime.now(UTC) - timedelta(seconds=10)
            artifact = await _make_keyframe_artifact(
                session,
                project=project,
                shot_id=shots[0].id,
                user=owner,
                attempt_no=2 if with_pending else 1,
            )
            artifact.created_at = datetime.now(UTC)
            # The identity review run that carries the human rejection.
            graph = await session.scalar(
                select(ProductionGraph).where(
                    ProductionGraph.project_id == project.id,
                    ProductionGraph.scope_type == "shot",
                    ProductionGraph.scope_entity_id == shots[0].id,
                )
            )
            assert graph is not None and graph.current_version_id is not None
            node = await session.scalar(
                select(GraphNode).where(
                    GraphNode.graph_version_id == graph.current_version_id,
                    GraphNode.node_key == "identity_review",
                )
            )
            if node is None:
                node = GraphNode(
                    graph_version_id=graph.current_version_id,
                    node_key="identity_review",
                    node_type="identity_review",
                    display_name="identity_review",
                    cacheable=False,
                )
                session.add(node)
                await session.flush()
            run = NodeRun(
                project_id=project.id,
                graph_version_id=graph.current_version_id,
                graph_node_id=node.id,
                attempt_no=1,
                idempotency_key=f"review-{uuid4().hex}",
                input_hash=uuid4().hex * 2,
                input_snapshot={
                    "shot_id": str(shots[0].id),
                    "node_key": "identity_review",
                    "upstream_artifact_id": str(artifact.id),
                },
                status="queued",
                output_summary={"status": "needs_human"},
                created_by=owner.id,
            )
            session.add(run)
            await session.flush()
            from app.execution.models import Artifact

            evidence = Artifact(
                project_id=project.id,
                artifact_type="image",
                storage_state="available",
                object_key=f"review/{uuid4().hex}",
                content_hash=uuid4().hex * 2,
                mime_type="image/png",
                byte_size=1,
                produced_by_run_id=run.id,
            )
            session.add(evidence)
            await session.flush()
            run.result_artifact_id = evidence.id
            run.status = "completed"
            await session.flush()
            await record_human_decision(
                session,
                project_id=project.id,
                shot_id=shots[0].id,
                artifact_id=artifact.id,
                review_node_run_id=run.id,
                review_kind="identity",
                decision="rejected",
                reason="人物脸部崩坏。",
                actor_id=owner.id,
                shot_version=shots[0].version,
                request_key=f"review:{uuid4().hex}",
            )
            await session.commit()
            return [str(shot.id) for shot in shots], str(pending.id) if pending else None

    shot_ids, pending_id = asyncio.run(seed_rejected_candidate())
    preview = client.get(f"{path}/preview", params={"stage": "image_keyframe"}).json()
    items = {item["shot_id"]: item for item in preview["items"]}
    rejected = items[shot_ids[0]]
    assert rejected["disposition"] == "skipped"
    assert rejected["reason"] == (
        "CANDIDATE_AWAITING_REVIEW" if with_pending else "CANDIDATE_REJECTED"
    )
    assert items[shot_ids[1]]["disposition"] == "ready"
    todos = client.get(f"/api/v1/projects/{project_id}/production-todos").json()
    todo_details = {item["shot_id"]: item for item in todos["items"]}
    if with_pending:
        assert todo_details[shot_ids[0]]["category"] == "awaiting_review"
        assert todo_details[shot_ids[0]]["artifact_id"] == pending_id
        assert todo_details[shot_ids[0]]["detail"] != "REVIEW_DECISION_REJECTED"
    else:
        assert todo_details[shot_ids[0]]["detail"] == "CANDIDATE_REJECTED"

    # Dispatch with the current preview: the rejected shot is not re-created.
    dispatched = client.post(
        path, headers={CSRF_HEADER: _csrf(client)}, json=_batch_dispatch_body(preview)
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["accepted_count"] == 1

    async def assert_rejected_shot_not_regenerated():
        async with factory() as session:
            runs = list((await session.scalars(select(NodeRun))).all())
            batch_runs = [run for run in runs if run.input_snapshot.get("paid_authorization")]
            assert len(batch_runs) == 1
            assert batch_runs[0].input_snapshot["shot_id"] == shot_ids[1]

    asyncio.run(assert_rejected_shot_not_regenerated())
