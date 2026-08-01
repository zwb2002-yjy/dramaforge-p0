"""Shipped product path using shared get_object_store() singleton."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery import models as _dm  # noqa: F401
from app.delivery.export_service import build_project_export
from app.events import models as _em  # noqa: F401
from app.events.models import OutboxEvent
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, NodeRun
from app.execution.product_path import execute_media_node_run
from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0, set_shot_lock
from app.execution.shot_review import local_rerun_from_node, start_shot_nodes
from app.production import models as _pm  # noqa: F401
from app.runtime.scheduler import AgentRunScheduler, WorkerRuntime
from app.shared.base import Base
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from app.workers.jobs import health_ping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


async def _seed_user_workspace(session: AsyncSession) -> tuple[User, UUID]:
    user = User(
        email=f"u-{uuid4().hex[:8]}@example.com",
        display_name="U",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"O-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    await session.commit()
    return user, workspace.id


@pytest.mark.asyncio
async def test_shipped_keyframe_via_creation_and_worker_entry(session: AsyncSession) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name=f"KF-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        idea="opening",
    )
    assert started.text_provider_operations == 0
    project_id = started.project_id
    rev = await CreationService(session).update_brief_manual(
        project_id=project_id, actor=user, logline="Neon rain hero"
    )
    rev = await CreationService(session).confirm_brief(
        project_id=project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "keyframe neon"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=project_id, plan_id=plan.id, actor=user
    )
    store = get_object_store()
    # Attach canonical so face path is two-source when keyframe runs
    from app.providers.fake import FakeFluxAdapter

    ad = FakeFluxAdapter()
    c = await ad.create({"prompt": "canonical lead", "kind": "keyframe"})
    await store.put_bytes(
        object_key=f"projects/{project_id}/canonical/lead.png",
        data=ad.blobs[c["remote_task_id"]],
        mime_type="image/png",
    )
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "canonical_object_key": f"projects/{project_id}/canonical/lead.png",
        "plan": {"prompt": "keyframe neon"},
    }
    await session.flush()
    # Unit tests: mock Arq (commit-then-enqueue still runs; no live Redis required)
    async def _fake_arq(self, node_run_id):  # type: ignore[no-untyped-def]
        return f"test-job:{node_run_id}"


    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(AgentRunScheduler, "_enqueue_node_run", _fake_arq)
    try:
        job_id = await AgentRunScheduler(session).enqueue_node_run_only(mat.node_run_id)
    finally:
        monkeypatch.undo()
    assert job_id and not str(job_id).startswith("local:")
    run_still = await session.get(NodeRun, mat.node_run_id)
    assert run_still is not None and run_still.status == "queued"
    await WorkerRuntime(session).process_one(mat.node_run_id)
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "completed"
    assert (run.output_summary or {}).get("source_commit") == "test-source-commit"
    art = await session.get(Artifact, run.result_artifact_id)
    assert art is not None
    assert art.byte_size > 8
    # SAME store Worker used
    data = await store.get_bytes(object_key=art.object_key)
    assert len(data) == art.byte_size

    exp = await build_project_export(
        session,
        project_id=project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
        require_approved=False,
    )
    assert exp.timeline_hash == (
        await build_project_export(
            session,
            project_id=project_id,
            requested_by=user.id,
            shot_subtitles=[("1", "Hi")],
            store=store,
            try_ffmpeg=False,
            require_approved=False,
        )
    ).timeline_hash


@pytest.mark.asyncio
async def test_lead_keyframe_passes_canonical_bytes_to_provider(session: AsyncSession) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name=f"Identity-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="lead portrait"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "lead portrait", "shots": []},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    canonical = b"canonical-reference-bytes"
    store = get_object_store()
    canonical_key = f"projects/{started.project_id}/canonical/identity.png"
    await store.put_bytes(object_key=canonical_key, data=canonical, mime_type="image/png")
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "canonical_object_key": canonical_key,
        "lead_identity_required": True,
    }

    class RecordingAdapter:
        provider = "recording"

        def __init__(self) -> None:
            self.request: dict[str, object] | None = None
            self.blobs = {"recording-keyframe": b"\x89PNG\r\n\x1a\nidentity"}

        async def create(self, request: dict[str, object]) -> dict[str, object]:
            self.request = request
            return {
                "remote_task_id": "recording-keyframe",
                "status": "succeeded",
                "identity_conditioning": "canonical_image_edit",
                "canonical_image_fingerprint": "fingerprint",
            }

        async def poll(self, remote_task_id: str) -> dict[str, object]:
            assert remote_task_id == "recording-keyframe"
            return {"status": "succeeded"}

        async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
            assert remote_task_id == "recording-keyframe"
            return {"amount": 0.0, "currency": "USD"}

    adapter = RecordingAdapter()
    await execute_media_node_run(session, node_run_id=run.id, store=store, flux=adapter)

    assert adapter.request is not None
    assert adapter.request["canonical_image_bytes"] == canonical
    assert adapter.request["canonical_image_mime"] == "image/png"


@pytest.mark.asyncio
async def test_ten_shot_full_nodes_and_lock(session: AsyncSession) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id,
        name=f"S4-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    shots = await produce_shots_p0(
        session, project_id=project.id, user_id=user.id, n=10
    )
    assert len(shots) == 10
    assert all(len(s.node_ids) == 9 for s in shots)
    assert all(s.face_checked and s.continuity_checked for s in shots)
    assert all(s.face_status is not None for s in shots)
    # Deliberate character mismatch must not score as near-identity
    mismatched = await produce_shots_p0(
        session,
        project_id=project.id,
        user_id=user.id,
        n=1,
        mismatch_face_on_shot=1,
    )
    assert mismatched[0].face_status in {"blocked", "needs_human", "warning"} or (
        mismatched[0].face_score is not None and mismatched[0].face_score < 0.95
    )
    for s in shots:
        for key in s.node_ids:
            assert key in s.run_ids and key in s.artifact_ids
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
            new_subtitle="Y",
            budget=Decimal("50"),
        )


@pytest.mark.asyncio
async def test_subtitle_rerun_with_unchanged_text_keeps_independent_artifacts(
    session: AsyncSession,
) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    project = await ProjectService(session).create_project(
        workspace_id=workspace_id,
        name=f"Subtitle-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    original_text = "The archive remembers everything."
    episode = Episode(project_id=project.id, episode_number=1, title="Episode")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Archive",
        time_of_day="night",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        sort_order=1,
        visual_description="archive room closeup",
        dialogue=original_text,
        status="in_production",
    )
    session.add(shot)
    await session.flush()
    first_run_ids = await start_shot_nodes(
        session,
        project_id=project.id,
        shot_id=shot.id,
        user_id=user.id,
        node_keys=["subtitle"],
    )
    assert len(first_run_ids) == 1
    await WorkerRuntime(session).process_one(first_run_ids[0])
    first_run = await session.get(NodeRun, first_run_ids[0])
    assert first_run is not None
    first_artifact = await session.get(Artifact, first_run.result_artifact_id)
    assert first_run is not None and first_run.status == "completed"
    assert first_artifact is not None

    rerun_keys, rerun_ids = await local_rerun_from_node(
        session,
        project_id=project.id,
        user_id=user.id,
        shot_id=shot.id,
        changed_node_key="subtitle",
    )
    assert rerun_keys[0] == "subtitle"
    subtitle_rerun_id = rerun_ids[rerun_keys.index("subtitle")]
    await WorkerRuntime(session).process_one(subtitle_rerun_id)
    rerun = await session.get(NodeRun, subtitle_rerun_id)
    assert rerun is not None
    rerun_artifact = await session.get(Artifact, rerun.result_artifact_id)
    assert rerun is not None and rerun.status == "completed"
    assert rerun_artifact is not None
    assert rerun.id != first_run.id
    assert rerun_artifact.id != first_artifact.id
    assert rerun_artifact.object_key != first_artifact.object_key
    assert rerun_artifact.content_hash != first_artifact.content_hash
    assert first_artifact.produced_by_run_id == first_run.id
    assert rerun_artifact.produced_by_run_id == rerun.id

    store = get_object_store()
    first_srt = (await store.get_bytes(object_key=first_artifact.object_key)).decode()
    rerun_srt = (await store.get_bytes(object_key=rerun_artifact.object_key)).decode()
    first_lines = first_srt.splitlines()
    rerun_lines = rerun_srt.splitlines()
    assert first_lines[0] == str(first_run.id.int)
    assert rerun_lines[0] == str(rerun.id.int)
    assert first_lines[1:] == rerun_lines[1:]
    assert first_lines[1] == "00:00:00,000 --> 00:00:02,000"
    assert original_text in first_lines[2]


@pytest.mark.asyncio
async def test_scheduler_drains_queued(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name=f"Sch-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        idea="x",
    )
    project_id = started.project_id
    rev = await CreationService(session).update_brief_manual(
        project_id=project_id, actor=user, logline="line"
    )
    await CreationService(session).confirm_brief(
        project_id=project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "p"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=project_id, plan_id=plan.id, actor=user
    )

    async def _fake_arq(self, node_run_id):  # type: ignore[no-untyped-def]
        return f"test-job:{node_run_id}"

    monkeypatch.setattr(AgentRunScheduler, "_enqueue_node_run", _fake_arq)
    n = await AgentRunScheduler(session).dispatch_pending(worker_id="test")
    assert n >= 1
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    assert run.status == "queued"
    await WorkerRuntime(session).process_queued()
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    assert run.status in {"completed", "failed", "needs_human"} or run.status == "completed"


@pytest.mark.asyncio
async def test_scheduler_skips_queued_runs_from_a_different_formal_source_commit(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import clear_settings_cache

    user, workspace_id = await _seed_user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name=f"Source-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        idea="x",
    )
    project_id = started.project_id
    rev = await CreationService(session).update_brief_manual(
        project_id=project_id, actor=user, logline="line"
    )
    await CreationService(session).confirm_brief(
        project_id=project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "p"},
    )
    current = await CreationService(session).confirm_plan_and_materialize(
        project_id=project_id, plan_id=plan.id, actor=user
    )
    current_run = await session.get(NodeRun, current.node_run_id)
    assert current_run is not None
    current_run.input_snapshot = {
        **current_run.input_snapshot,
        "source_commit": "current-source",
    }

    old_run = NodeRun(
        project_id=current_run.project_id,
        graph_version_id=current_run.graph_version_id,
        graph_node_id=current_run.graph_node_id,
        attempt_no=2,
        idempotency_key=f"old-source:{uuid4()}",
        input_hash="f" * 64,
        status="queued",
        input_snapshot={"source_commit": "old-source"},
        created_by=user.id,
    )
    session.add(old_run)
    await session.commit()

    enqueued: list[UUID] = []

    async def _fake_arq(self, node_run_id: UUID) -> str:  # type: ignore[no-untyped-def]
        _ = self
        enqueued.append(node_run_id)
        return f"test-job:{node_run_id}"

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DRAMAFORGE_SOURCE_COMMIT", "current-source")
    monkeypatch.setattr(AgentRunScheduler, "_enqueue_node_run", _fake_arq)
    clear_settings_cache()
    try:
        await AgentRunScheduler(session).dispatch_pending(worker_id="test")
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        clear_settings_cache()

    assert current_run.id in enqueued
    assert old_run.id not in enqueued


@pytest.mark.asyncio
async def test_explicit_enqueue_reuses_materialization_outbox(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, workspace_id = await _seed_user_workspace(session)
    started = await CreationService(session).start_project(
        workspace_id=workspace_id,
        name=f"Outbox-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        idea="opening",
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="Neon rain"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "keyframe neon"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )

    async def _fake_arq(self, node_run_id):  # type: ignore[no-untyped-def]
        return f"test-job:{node_run_id}"

    monkeypatch.setattr(AgentRunScheduler, "_enqueue_node_run", _fake_arq)
    await AgentRunScheduler(session).enqueue_node_run_only(mat.node_run_id)

    outbox_rows = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.topic == "node_run.enqueue")
        )
    ).scalars().all()
    matching = [
        row
        for row in outbox_rows
        if str((row.payload or {}).get("node_run_id")) == str(mat.node_run_id)
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_health_ping_job() -> None:
    assert (await health_ping({}))["status"] == "ok"


def test_rls_migration_and_worker_jobs_registered() -> None:
    from pathlib import Path

    from app.workers.jobs import JOB_FUNCTIONS

    root = Path(__file__).resolve().parents[2]
    mig = root / "alembic" / "versions" / "20260721_0005_rls_policies.py"
    assert mig.is_file()
    text = mig.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in text
    names = {getattr(f, "__name__", str(f)) for f in JOB_FUNCTIONS}
    assert "execute_node_run" in names
