"""Export must read Worker frames from shared get_object_store (not empty store)."""

from __future__ import annotations

import shutil
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.access.projects import ProjectService
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery import models as _dm  # noqa: F401
from app.delivery.export_service import build_project_export
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, NodeRun
from app.production import models as _pm  # noqa: F401
from app.runtime.scheduler import WorkerRuntime
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests


@pytest.fixture
async def session() -> AsyncSession:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()
    reset_object_store_for_tests()


@pytest.mark.asyncio
async def test_export_default_store_sees_worker_png_frames(session: AsyncSession) -> None:
    user = User(
        email=f"ex-{uuid4().hex[:8]}@example.com",
        display_name="E",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name="ExOrg")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    started = await CreationService(session).start_project(
        organization_id=org.id, name="Ex", aspect_ratio="9:16", actor=user
    )
    rev = await CreationService(session).update_brief_manual(
        project_id=started.project_id, actor=user, logline="frames"
    )
    await CreationService(session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "export frame png"},
    )
    mat = await CreationService(session).confirm_plan_and_materialize(
        project_id=started.project_id, plan_id=plan.id, actor=user
    )
    await WorkerRuntime(session).process_one(mat.node_run_id)
    run = await session.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "completed"
    art = await session.get(Artifact, run.result_artifact_id)
    assert art is not None
    # Worker used singleton — export with store=None must still see bytes
    shared = get_object_store()
    data = await shared.get_bytes(object_key=art.object_key)
    assert data[:4] == b"\x89PNG"
    exp = await build_project_export(
        session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Hi")],
        store=None,  # force default get_object_store()
        try_ffmpeg=True,
        require_approved=False,
    )
    assert exp.timeline_hash and exp.package_hash
    # Must not fail with empty-store no-frames when PNG exists in singleton
    assert exp.mp4_error != "FFMPEG_NO_READABLE_FRAMES"
    if shutil.which("ffmpeg"):
        # Either real MP4 or ffmpeg runtime failure — not missing frames
        assert exp.mp4_error is None or exp.mp4_error.startswith("FFMPEG_")
        if exp.mp4_error is None:
            assert exp.mp4_object_key and exp.mp4_hash
    else:
        assert exp.mp4_error == "FFMPEG_NOT_FOUND"
