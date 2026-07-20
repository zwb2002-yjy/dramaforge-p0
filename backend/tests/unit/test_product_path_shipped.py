"""Unit tests for shipped product path (CreationService + Worker execute + export).

SQLite create_all only — not a substitute for PG RLS Gate.
Drives real app.execution.product_path / shot_p0 / export_service / CreationService.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.access.projects import ProjectService
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery.export_service import build_project_export
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, NodeRun
from app.execution.product_path import execute_keyframe_node_run
from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0
from app.production import models as _pm  # noqa: F401
from app.runtime.scheduler import AgentRunScheduler
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore
from app.workers.jobs import health_ping


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_user_org(session: AsyncSession) -> tuple[User, UUID]:
    user = User(
        email=f"u-{uuid4().hex[:8]}@example.com",
        display_name="U",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"O-{uuid4().hex[:6]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    await session.commit()
    return user, org.id


@pytest.mark.asyncio
async def test_shipped_keyframe_via_creation_and_worker_entry(session: AsyncSession) -> None:
    user, org_id = await _seed_user_org(session)
    started = await CreationService(session).start_project(
        organization_id=org_id,
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
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    assert run.status == "queued"

    store = InMemoryObjectStore()
    result = await execute_keyframe_node_run(
        session, node_run_id=mat.node_run_id, store=store
    )
    await session.commit()
    assert result.byte_size > 8
    assert len(result.content_hash) == 64
    assert not result.object_key.startswith("http")
    art = await session.get(Artifact, result.artifact_id)
    assert art is not None
    assert art.byte_size == result.byte_size
    data = await store.get_bytes(object_key=art.object_key)
    assert len(data) == art.byte_size

    exp = await build_project_export(
        session,
        project_id=project_id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
    )
    assert exp.timeline_hash and exp.srt_hash and exp.package_hash
    assert exp.mp4_error == "FFMPEG_SKIPPED"
    assert exp.source_artifact_ids
    exp2 = await build_project_export(
        session,
        project_id=project_id,
        shot_subtitles=[("1", "Hi")],
        store=store,
        try_ffmpeg=False,
    )
    assert exp2.timeline_hash == exp.timeline_hash


@pytest.mark.asyncio
async def test_ten_shot_full_nodes_and_lock(session: AsyncSession) -> None:
    user, org_id = await _seed_user_org(session)
    project = await ProjectService(session).create_project(
        organization_id=org_id,
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
    kf = shots[0].run_ids["keyframe"]
    await rework_subtitle_only_p0(
        session,
        project_id=project.id,
        user_id=user.id,
        shot=shots[0],
        new_subtitle="X",
        budget=Decimal("50"),
    )
    assert shots[0].run_ids["keyframe"] == kf
    shots[0].locked = True
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
async def test_scheduler_drains_queued(session: AsyncSession) -> None:
    user, org_id = await _seed_user_org(session)
    started = await CreationService(session).start_project(
        organization_id=org_id,
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
    n = await AgentRunScheduler(session).dispatch_pending(worker_id="test")
    assert n >= 1
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_health_ping_job() -> None:
    assert (await health_ping({}))["status"] == "ok"


def test_rls_migration_and_worker_jobs_registered() -> None:
    """Structural: RLS migration + Arq jobs exist on shipped tree."""
    from pathlib import Path

    from app.workers.jobs import JOB_FUNCTIONS

    root = Path(__file__).resolve().parents[2]
    mig = root / "alembic" / "versions" / "20260721_0005_rls_policies.py"
    assert mig.is_file()
    text = mig.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    names = {getattr(f, "__name__", str(f)) for f in JOB_FUNCTIONS}
    assert "execute_node_run" in names
    assert "dispatch_outbox" in names
