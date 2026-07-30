"""Shared P0 gate harness — one store, one project spine for all matrix tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.access.models import User, Workspace
from app.creation.service import CreationService
from app.delivery.export_service import build_project_export
from app.execution.models import NodeRun
from app.runtime.scheduler import AgentRunScheduler, WorkerRuntime
from app.shared.base import Base
from app.shared.db import set_rls_context
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass
class HarnessProject:
    user: User
    workspace_id: UUID
    project_id: UUID
    session: AsyncSession


async def make_sqlite_session() -> tuple:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = factory()
    return engine, session


async def bootstrap_project(session: AsyncSession, *, name: str | None = None) -> HarnessProject:
    reset_object_store_for_tests()
    user = User(
        email=f"h-{uuid4().hex[:8]}@example.com",
        display_name="H",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Org-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    await session.commit()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    started = await CreationService(session).start_project(
        workspace_id=workspace.id,
        name=name or f"P0-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        idea="gate harness",
    )
    await set_rls_context(
        session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=started.project_id,
    )
    return HarnessProject(
        user=user,
        workspace_id=workspace.id,
        project_id=started.project_id,
        session=session,
    )


async def run_first_frame_to_completion(h: HarnessProject) -> NodeRun:
    """Brief→Plan→enqueue→WorkerRuntime (shared store)."""
    s = h.session
    user = h.user
    pid = h.project_id
    rev = await CreationService(s).update_brief_manual(
        project_id=pid, actor=user, logline="Neon rain opening shot"
    )
    await CreationService(s).confirm_brief(
        project_id=pid, revision_id=rev.id, actor=user
    )
    plan = await CreationService(s).create_or_update_plan_manual(
        project_id=pid,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "cinematic neon rain keyframe"},
    )
    mat = await CreationService(s).confirm_plan_and_materialize(
        project_id=pid, plan_id=plan.id, actor=user
    )
    # Attach a canonical for face path on keyframe via snapshot key is optional for S2
    # Keyframe may be needs_human without canonical; still produces Artifact.
    job = await AgentRunScheduler(s).enqueue_node_run_only(mat.node_run_id)
    assert job
    run = await s.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "queued"
    await WorkerRuntime(s).process_one(mat.node_run_id)
    run = await s.get(NodeRun, mat.node_run_id)
    assert run is not None and run.status == "completed"
    assert run.result_artifact_id
    return run


async def export_project(h: HarnessProject, *, try_ffmpeg: bool = False):
    return await build_project_export(
        h.session,
        project_id=h.project_id,
        requested_by=h.user.id,
        shot_subtitles=[("1", "Opening")],
        store=get_object_store(),
        try_ffmpeg=try_ffmpeg,
        require_approved=False,
    )
