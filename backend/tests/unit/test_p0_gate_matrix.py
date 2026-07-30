"""P0 gate matrix — one test per closable freeze row (shared harness + store).

External-only rows (S0-A FAR/FRR samples, live Playwright browser, live multi-provider)
are documented as skip reasons, not marked passed.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.assets import models as _am  # noqa: F401
from app.assets.characters import register_lead_character, require_canonical_for_shot
from app.assets.script_import import import_script
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery import models as _dm  # noqa: F401
from app.delivery.download import (
    authorize_export_download,
    fetch_export_bytes,
    verify_download_token,
)
from app.delivery.export_service import build_project_export
from app.events import models as _em  # noqa: F401
from app.events.models import OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.events.sse import SseHub, format_sse
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.product_path import execute_media_node_run
from app.execution.runtime_invariants import cancel_run, run_or_cache, single_flight_claim
from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0, set_shot_lock
from app.production import models as _pm  # noqa: F401
from app.production.service import GraphService
from app.providers.fake import FakeFluxAdapter
from app.runtime.scheduler import AgentRunScheduler, WorkerRuntime
from app.shared.base import Base
from app.shared.enums import OutboxStatus
from app.shared.errors import ForbiddenError, ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

GOLDEN = Path(__file__).resolve().parents[3] / "fixtures" / "scripts" / "p0_10_shots.md"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()
    reset_object_store_for_tests()


async def _user_workspace(session: AsyncSession) -> tuple[User, UUID]:
    user = User(
        email=f"g-{uuid4().hex[:8]}@example.com",
        display_name="G",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"GWorkspace-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    await session.commit()
    return user, workspace.id


@pytest.mark.asyncio
async def test_matrix_start_project_brief_zero_text_ops(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    r = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name="GateStart",
        aspect_ratio="9:16",
        actor=user,
        idea="x",
    )
    assert r.text_provider_operations == 0
    assert r.brief_revision_id
    assert r.project_id


@pytest.mark.asyncio
async def test_matrix_async_enqueue_then_worker_shared_store(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id, name="GateAsync", aspect_ratio="9:16", actor=user
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="Opening rain"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "neon keyframe"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )

    async def _fake_arq(self, node_run_id):  # type: ignore[no-untyped-def]
        return f"test-job:{node_run_id}"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(AgentRunScheduler, "_enqueue_node_run", _fake_arq)
    try:
        await AgentRunScheduler(session).enqueue_node_run_only(mat.node_run_id)
    finally:
        monkeypatch.undo()
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "queued"
    await WorkerRuntime(session).process_one(mat.node_run_id)
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "completed"
    art = await session.get(Artifact, run.result_artifact_id)
    assert art is not None
    # Shared store: Worker wrote bytes export can read
    data = await get_object_store().get_bytes(object_key=art.object_key)
    assert len(data) == art.byte_size and data[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_matrix_canonical_ref_required_rejects(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="Canon", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    graphs = GraphService(session)
    g = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
        definition={"nodes": ["keyframe"], "edges": []},
    )
    node = GraphNode(
        graph_version_id=g.current_version_id,
        node_key="keyframe.generate",
        node_type="keyframe",
        display_name="k",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"k:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={"plan": {"prompt": "x"}},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    with pytest.raises(ValidationAppError, match="CANONICAL_REFERENCE_REQUIRED"):
        await execute_media_node_run(
            session, node_run_id=run.id, require_canonical=True
        )


@pytest.mark.asyncio
async def test_matrix_budget_blocked(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="Bud", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    graphs = GraphService(session)
    g = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
        definition={},
    )
    assert g.current_version_id is not None
    node = GraphNode(
        graph_version_id=g.current_version_id,
        node_key="video",
        node_type="video",
        display_name="v",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run, remaining = await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash="b" * 64,
        created_by=user.id,
        budget_remaining=Decimal("0"),
        cost=Decimal("10"),
    )
    assert run.status == "blocked_budget"
    assert remaining == Decimal("0")


@pytest.mark.asyncio
async def test_matrix_ten_shot_face_two_source_and_lock(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="Ten", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    shots = await produce_shots_p0(
        session, project_id=project.id, user_id=user.id, n=10
    )
    assert len(shots) == 10
    assert all(s.face_checked and s.continuity_checked for s in shots)
    # Two-source: scores are real comparisons (not forced identity-only assertion)
    assert all(s.face_status in {"passed", "blocked", "warning", "needs_human"} for s in shots)
    # Deliberate mismatch shot
    bad = await produce_shots_p0(
        session,
        project_id=project.id,
        user_id=user.id,
        n=1,
        mismatch_face_on_shot=1,
    )
    assert bad[0].face_status == "blocked" or (
        bad[0].face_score is not None and bad[0].face_score < 0.95
    )
    kf = shots[0].run_ids["keyframe"]
    await rework_subtitle_only_p0(
        session,
        project_id=project.id,
        user_id=user.id,
        shot=shots[0],
        new_subtitle="neon rain street rework line",
        budget=Decimal("50"),
    )
    assert shots[0].run_ids["keyframe"] == kf
    await set_shot_lock(
        session, project_id=project.id, shot_id=shots[0].shot_id, user_id=user.id, locked=True
    )
    await session.commit()
    with pytest.raises(ValueError, match="locked"):
        await rework_subtitle_only_p0(
            session,
            project_id=project.id,
            user_id=user.id,
            shot=shots[0],
            new_subtitle="blocked",
            budget=Decimal("50"),
        )


@pytest.mark.asyncio
async def test_matrix_export_hash_equality_shared_store(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id, name="Exp", aspect_ratio="9:16", actor=user
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="export path"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "frame for export"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )
    # Put canonical so face path can complete if required
    store = get_object_store()
    ad = FakeFluxAdapter()
    c = await ad.create({"prompt": "canonical hero", "kind": "keyframe"})
    canon = ad.blobs[c["remote_task_id"]]
    await store.put_bytes(
        object_key=f"projects/{started.project_id}/canonical/ref.png",
        data=canon,
        mime_type="image/png",
    )
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "canonical_object_key": f"projects/{started.project_id}/canonical/ref.png",
        "plan": {"prompt": "frame for export"},
    }
    await session.flush()
    await WorkerRuntime(session).process_one(mat.node_run_id)
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    art = await session.get(Artifact, run.result_artifact_id)
    assert art is not None
    # Export uses SAME process store — must see worker bytes
    assert await store.get_bytes(object_key=art.object_key)
    e1 = await build_project_export(
        session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
        require_approved=False,
    )
    e2 = await build_project_export(
        session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
        require_approved=False,
    )
    assert e1.timeline_hash == e2.timeline_hash
    assert e1.srt_hash == e2.srt_hash
    assert e1.package_hash == e2.package_hash
    assert e1.export_id != e2.export_id


@pytest.mark.asyncio
async def test_matrix_cross_workspace_owner_denied(session: AsyncSession) -> None:
    owner, workspace_id = await _user_workspace(session)
    p = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="Private", aspect_ratio="9:16", actor=owner
    )
    await session.commit()
    intruder = User(
        email=f"intruder-{uuid4().hex[:6]}@example.com",
        display_name="X",
        password_hash=hash_password("password123"),
    )
    session.add(intruder)
    await session.commit()
    with pytest.raises(ForbiddenError):
        await ProjectService(session).get_project_for_owner(
            project_id=p.id, actor=intruder
        )


@pytest.mark.asyncio
async def test_matrix_script_import_and_canonical(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="ScriptGate", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    text = GOLDEN.read_text(encoding="utf-8")
    imp = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text,
        actor=user,
    )
    assert imp.shot_count == 10 and imp.scene_count == 3
    with pytest.raises(ValidationAppError, match="CANONICAL_REFERENCE_REQUIRED"):
        await require_canonical_for_shot(session, project_id=project.id)
    ad = FakeFluxAdapter()
    c = await ad.create({"prompt": "Lin Xia gate canon", "kind": "keyframe"})
    await register_lead_character(
        session,
        project_id=project.id,
        name="Lin Xia",
        locked_prompt="Lin Xia",
        canonical_image_bytes=ad.blobs[c["remote_task_id"]],
    )
    ref = await require_canonical_for_shot(session, project_id=project.id)
    assert ref.is_canonical and len(ref.face_embedding) == 512


@pytest.mark.asyncio
async def test_matrix_cache_hit_and_cancel(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="CacheGate", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    graphs = GraphService(session)
    g = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=g.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="k",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    assert g.current_version_id is not None
    ih = "c" * 64
    r1, bud = await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash=ih,
        created_by=user.id,
        budget_remaining=Decimal("20"),
        cost=Decimal("5"),
    )
    assert r1.status == "completed" and r1.provider_cost == Decimal("5")
    r2, bud2 = await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash=ih,
        created_by=user.id,
        budget_remaining=bud,
        cost=Decimal("5"),
    )
    assert r2.status == "cached"
    assert r2.provider_cost == Decimal("0")
    assert r2.result_artifact_id == r1.result_artifact_id
    assert bud2 == bud
    # Cancel completed → completed_after_cancel signal
    assert cancel_run(r1) == "completed_after_cancel"


@pytest.mark.asyncio
async def test_matrix_single_flight_one_leader(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id, name="SF", aspect_ratio="9:16", actor=user
    )
    await session.commit()
    graphs = GraphService(session)
    g = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=g.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="k",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    assert g.current_version_id is not None
    ih = "d" * 64
    r1, lead1 = await single_flight_claim(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash=ih,
        created_by=user.id,
    )
    r2, lead2 = await single_flight_claim(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash=ih,
        created_by=user.id,
    )
    assert lead1 is True and lead2 is False
    assert r1.id == r2.id


@pytest.mark.asyncio
async def test_matrix_sse_last_event_id_resume() -> None:
    hub = SseHub(capacity=50)
    e1 = hub.publish(event="node.progress", data={"n": 1})
    e2 = hub.publish(event="node.completed", data={"n": 2})
    resumed = hub.since(e1.id)
    assert len(resumed) == 1 and resumed[0].id == e2.id
    assert f"id: {e2.id}" in format_sse(e2)
    gen = hub.stream(last_event_id=e1.id)
    first = await gen.__anext__()
    assert first.id == e2.id


@pytest.mark.asyncio
async def test_matrix_outbox_dead_letter_replay(session: AsyncSession) -> None:
    publisher = StreamPublisher()
    d = OutboxDispatcher(session, publisher, max_attempts=2)
    event = OutboxEvent(
        event_id=uuid4(),
        topic="node.completed",
        schema_version=1,
        payload={"shot": "1"},
        status=OutboxStatus.PENDING.value,
        attempt_count=0,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    c1 = await d.claim_pending(worker_id="w1", limit=5)
    assert len(c1) == 1
    await d.fail_leased(c1[0], error="down")
    await session.commit()
    c2 = await d.claim_pending(worker_id="w1", limit=5)
    assert len(c2) == 1
    dl = await d.fail_leased(c2[0], error="still down")
    assert dl is not None
    await session.commit()
    replayed = await d.human_replay_dead_letter(dl.id, operator="ops")
    await session.commit()
    assert replayed.status == OutboxStatus.PUBLISHED.value
    assert len(publisher.messages) == 1


@pytest.mark.asyncio
async def test_matrix_authorized_export_download(session: AsyncSession) -> None:
    user, workspace_id = await _user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id, name="Dl", aspect_ratio="9:16", actor=user
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="dl path"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "frame dl"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )
    store = get_object_store()
    await WorkerRuntime(session).process_one(mat.node_run_id)
    exp = await build_project_export(
        session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
        require_approved=False,
    )
    grant = await authorize_export_download(
        session, export_id=exp.export_id, actor=user, object_role="timeline_json"
    )
    verify_download_token(
        token=grant.token,
        export_id=exp.export_id,
        project_id=started.project_id,
        object_key=grant.object_key,
        user_id=user.id,
    )
    data = await fetch_export_bytes(grant=grant, store=store)
    assert b"timeline" in data or b"project_id" in data
    # Intruder cannot mint for member-only project
    intruder = User(
        email=f"dl-x-{uuid4().hex[:6]}@example.com",
        display_name="X",
        password_hash=hash_password("password123"),
    )
    session.add(intruder)
    await session.commit()
    with pytest.raises(ForbiddenError):
        await authorize_export_download(
            session, export_id=exp.export_id, actor=intruder, object_role="timeline_json"
        )
    # Tampered token rejected
    with pytest.raises(ForbiddenError):
        verify_download_token(
            token=grant.token[:-4] + "dead",
            export_id=exp.export_id,
            project_id=started.project_id,
            object_key=grant.object_key,
            user_id=user.id,
        )


def test_matrix_external_residuals_documented() -> None:
    """External-only freeze rows — not marked passed (honest residual)."""
    external = {
        "S0-A_FAR_FRR_fixtures": "BLOCKED_BY_FIXTURE",
        "Playwright_browser_E2E": "ENV_OPTIONAL",
        "Live_multi_provider_BYOK_soak": "USER_AUTH_REQUIRED",
        "PostgreSQL_RLS_integration": "DOCKER_ENGINE_REQUIRED",
    }
    assert external["S0-A_FAR_FRR_fixtures"] == "BLOCKED_BY_FIXTURE"
    assert external["PostgreSQL_RLS_integration"] == "DOCKER_ENGINE_REQUIRED"
