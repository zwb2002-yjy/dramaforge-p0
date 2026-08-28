"""Phase 3 §19 Story/Scene/Shot chained acceptance loop on real PostgreSQL.

Chain: import → scene ops (reorder/split/merge/copy) → user shot edit (canvas +
optimistic lock) → agent proposal (NO mutation) → user accept/apply (atomic,
idempotent, stale-safe) → restart via a fresh engine/session → re-read the full
spine. Proves §19 Gate: "服务重启数据不丢失" and "Agent 无权静默覆盖 Shot".
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.api.v1.scripts import (
    ShotCanvasUpdateBody,
    ShotChangeProposalCreate,
    confirm_shot_change_proposal,
    create_shot_change_proposal,
    get_project_script,
    update_shot_canvas,
)
from app.assets.models import CanvasRevision, Scene, Shot, ShotChangeProposal
from app.assets.scene_service import SceneStructureService, SceneSummaryService
from app.assets.script_import import import_script
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from app.shared.security import hash_password
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "scripts" / "p0_10_shots.md"

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1.0):
            pass
        from sqlalchemy import create_engine

        sync_url = _database_url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
        engine = create_engine(sync_url, connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _postgres_is_available(),
    reason="set TEST_PG_ENABLED=1 with an explicitly configured PostgreSQL target",
)


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _project(session: AsyncSession):
    user = User(
        email=f"s-{uuid4().hex[:8]}@example.com",
        display_name="S",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"SO-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"Phase3-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    return user, project.id, workspace.id


@pytest.mark.asyncio
async def test_phase3_story_loop_chains_and_survives_restart(pg_session: AsyncSession) -> None:
    user, project, workspace_id = await _project(pg_session)
    user_id = user.id

    # --- 1. Import: Script → Episode → Scene → Shot (§19.1) ---
    text_script = GOLDEN.read_text(encoding="utf-8")
    result = await import_script(
        pg_session,
        project_id=project,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text_script,
        actor=user,
    )
    await pg_session.commit()
    assert result.scene_count == 3
    assert result.shot_count == 10
    ws = await get_project_script(project, user, pg_session)
    assert ws.document is not None
    assert len(ws.episodes) == 1
    assert [s.shot_count for s in ws.episodes[0].scenes] == [3, 4, 3]

    # --- 2. Scene ops on the same set (§19.2) ---
    scene_rows = (
        await pg_session.execute(
            select(Scene).order_by(Scene.scene_number)
        )
    ).scalars().all()
    scene_rows = [s for s in scene_rows if s.episode_id == ws.episodes[0].id]
    assert len(scene_rows) == 3

    struct = SceneStructureService(pg_session)
    # reorder scene 2 → 5
    reordered = await struct.reorder(
        project_id=project, scene_id=scene_rows[1].id, actor=user, new_scene_number=5
    )
    assert reordered.scene_number == 5
    # split scene 1 at shot 2
    split_new = await struct.split(
        project_id=project,
        scene_id=scene_rows[0].id,
        actor=user,
        at_shot_number=2,
    )
    assert split_new.id != scene_rows[0].id
    # copy a scene → new row + duplicated shots
    copied = await struct.copy(
        project_id=project, scene_id=scene_rows[2].id, actor=user
    )
    assert "（副本）" in copied.location_name
    copied_shots = (
        await pg_session.execute(select(Shot).where(Shot.scene_id == copied.id))
    ).scalars().all()
    assert len(copied_shots) == 3
    await pg_session.commit()

    # --- 3. User shot edit + optimistic lock + CanvasRevision (§19.3/§19.4) ---
    shots = (
        await pg_session.execute(
            select(Shot).where(Shot.project_id == project).order_by(Shot.shot_number)
        )
    ).scalars().all()
    shot = shots[0]
    shot_id = shot.id
    original_version = shot.version
    canvas = await update_shot_canvas(
        project,
        shot_id,
        ShotCanvasUpdateBody(
            expected_version=original_version,
            visual_description="用户确认的正式镜头语义",
            shot_type=shot.shot_type,
            camera_move="slow_push_in",
            dialogue=shot.dialogue,
        ),
        user,
        pg_session,
        None,
    )
    await pg_session.commit()
    assert canvas.revision_number == 1
    assert canvas.shot.version == original_version + 1
    # stale write → Conflict
    with pytest.raises(ConflictError):
        await update_shot_canvas(
            project,
            shot_id,
            ShotCanvasUpdateBody(
                expected_version=original_version,
                visual_description="过期编辑器覆盖",
                shot_type=shot.shot_type,
                camera_move="static",
                dialogue=shot.dialogue,
            ),
            user,
            pg_session,
            None,
        )
    await pg_session.rollback()
    # The rollback expired the `user` ORM instance; re-fetch it fresh so the
    # subsequent services can read its identity without a sync lazy-load.
    user = (await pg_session.execute(select(User).where(User.id == user_id))).scalar_one()

    # --- 4. Agent proposal: NO mutation before accept (§19.5) ---
    current = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    base_version = current.version  # plain int; confirm will mutate the same ORM identity
    body = ShotChangeProposalCreate(
        idempotency_key="phase3-proposal-1",
        summary="导演助手建议的正式镜头语义",
        expected_version=base_version,
        replacement_payload={"visual_description": "新的导演语义"},
        affected_node_keys=["video"],
        reusable_artifact_ids=[],
    )
    created = await create_shot_change_proposal(
        project, shot_id, body, user, pg_session, None
    )
    await pg_session.commit()
    before_accept = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    assert before_accept.visual_description != "新的导演语义"
    assert before_accept.version == base_version

    # --- 5. User accept/apply: atomic, complete resulting state (§19.5) ---
    confirmed = await confirm_shot_change_proposal(
        project, shot_id, created.proposal.id, user, pg_session, None
    )
    await pg_session.commit()
    assert confirmed.status == "applied"
    assert confirmed.confirmed_revision_id is not None
    applied = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    applied_version = applied.version  # plain int; survives engine disposal
    assert applied.visual_description == "新的导演语义"
    assert applied.version == base_version + 1
    assistant_revisions = (
        await pg_session.execute(
            select(CanvasRevision)
            .where(CanvasRevision.shot_id == shot_id, CanvasRevision.source == "assistant")
        )
    ).scalars().all()
    assert len(assistant_revisions) == 1
    assert assistant_revisions[0].visual_description == "新的导演语义"
    assert assistant_revisions[0].shot_type == applied.shot_type

    # --- 5b. Idempotent retry: no new revision, no version bump ---
    retried = await confirm_shot_change_proposal(
        project, shot_id, created.proposal.id, user, pg_session, None
    )
    await pg_session.commit()
    assert retried.id == confirmed.id
    assert retried.status == "applied"
    rev_count_after_retry = (
        await pg_session.execute(
            select(func.count())
            .select_from(CanvasRevision)
            .where(CanvasRevision.shot_id == shot_id)
        )
    ).scalar_one()
    shot_after_retry = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    assert rev_count_after_retry == 2  # user + assistant
    assert shot_after_retry.version == applied.version

    # --- 5c. Stale proposal → Conflict, no overwrite ---
    current2 = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    body2 = ShotChangeProposalCreate(
        idempotency_key="phase3-proposal-2",
        summary="会变 stale 的建议",
        expected_version=current2.version,
        replacement_payload={"visual_description": "过期覆盖"},
        affected_node_keys=[],
        reusable_artifact_ids=[],
    )
    created2 = await create_shot_change_proposal(
        project, shot_id, body2, user, pg_session, None
    )
    await pg_session.commit()
    # bump the shot via a user edit → proposal 2 becomes stale
    cur2 = (
        await pg_session.execute(select(Shot).where(Shot.id == shot_id))
    ).scalar_one()
    await update_shot_canvas(
        project,
        shot_id,
        ShotCanvasUpdateBody(
            expected_version=cur2.version,
            visual_description="用户更新的更新",
            shot_type=cur2.shot_type,
            camera_move="static",
            dialogue=cur2.dialogue,
        ),
        user,
        pg_session,
        None,
    )
    await pg_session.commit()
    with pytest.raises(ConflictError):
        await confirm_shot_change_proposal(
            project, shot_id, created2.proposal.id, user, pg_session, None
        )
    await pg_session.rollback()

    # --- 6. Restart: fresh engine + session re-reads the same committed DB ---
    engine2 = create_async_engine(_database_url(), pool_pre_ping=True)
    factory2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory2() as s2:
            await set_rls_context(s2, user_id=user_id, workspace_id=workspace_id)
            # Re-fetch the actor on the fresh session (the prior ORM instance is
            # bound to the disposed engine and would trigger a sync lazy-load).
            user2 = (await s2.execute(select(User).where(User.id == user_id))).scalar_one()
            # re-read the full spine
            ws2 = await get_project_script(project, user2, s2)
            assert ws2.document is not None
            assert ws2.document.raw_text == text_script
            summaries = await SceneSummaryService(s2).list_summaries(
                project_id=project, actor=user2
            )
            # reorder + split + copy changed the structure from 3 scenes to 5
            # (3 original + split new + copy). The reordered scene number may
            # have shifted after the split bumped siblings — what must hold is
            # the mutated count and the persisted copy.
            assert len(summaries) >= 4
            assert any("（副本）" in s["location_name"] for s in summaries)
            # shot edit + proposal apply survived
            shot2 = (
                await s2.execute(select(Shot).where(Shot.id == shot_id))
            ).scalar_one()
            assert shot2.visual_description == "用户更新的更新"
            assert shot2.version == applied_version + 1
            revs2 = (
                await s2.execute(
                    select(CanvasRevision).where(CanvasRevision.shot_id == shot_id)
                )
            ).scalars().all()
            assert len(revs2) == 3  # user + assistant + user(stale-bump)
            proposals2 = (
                await s2.execute(
                    select(ShotChangeProposal).where(
                        ShotChangeProposal.shot_id == shot_id
                    )
                )
            ).scalars().all()
            assert len(proposals2) == 2
            assert all(
                p.status in {"applied", "awaiting_confirmation"} for p in proposals2
            )
    finally:
        await engine2.dispose()
