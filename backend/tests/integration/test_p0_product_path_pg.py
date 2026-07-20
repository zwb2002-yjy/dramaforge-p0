"""P0 product path on real PostgreSQL: start → brief/plan → worker keyframe → export.

Requires Docker postgres. Captures evidence for Gate (async path, not request-thread spike).
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.access.service import AccessService
from app.creation.service import CreationService
from app.delivery.export_service import build_project_export
from app.execution.models import Artifact, NodeRun
from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0
from app.runtime.scheduler import AgentRunScheduler
from app.shared.db import set_rls_context
from app.shared.enums import MemberRole
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore

DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def _pg_up() -> bool:
    try:
        from sqlalchemy import create_engine

        sync = _url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
        eng = create_engine(sync, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_up(), reason="PostgreSQL unavailable")


@pytest.fixture
async def pg_session() -> AsyncSession:
    engine = create_async_engine(_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_async_keyframe_product_path(pg_session: AsyncSession) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"p0-{suffix}@example.com",
        display_name="P0",
        password_hash=hash_password("password123"),
    )
    pg_session.add(user)
    await pg_session.flush()
    org = Organization(name=f"P0Org-{suffix}")
    pg_session.add(org)
    await pg_session.flush()
    pg_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    await pg_session.commit()

    await set_rls_context(
        pg_session, user_id=user.id, organization_id=org.id
    )
    started = await CreationService(pg_session).start_project(
        organization_id=org.id,
        name=f"P0Proj-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="neon rain opening",
    )
    assert started.text_provider_operations == 0
    assert started.brief_revision_id

    await set_rls_context(
        pg_session,
        user_id=user.id,
        organization_id=org.id,
        project_id=started.project_id,
    )
    rev = await CreationService(pg_session).update_brief_manual(
        project_id=started.project_id,
        actor=user,
        logline="A hero walks into neon rain",
    )
    rev = await CreationService(pg_session).confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    assert rev.status == "confirmed"
    plan = await CreationService(pg_session).create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        plan_body={"prompt": "cinematic keyframe neon rain", "shots": 1},
    )
    confirmed = await CreationService(pg_session).confirm_plan_and_materialize(
        project_id=started.project_id,
        plan_id=plan.id,
        actor=user,
        materialization_ops=["create_shot_stub", "enqueue_keyframe"],
    )
    run = await pg_session.get(NodeRun, confirmed.node_run_id)
    assert run is not None
    assert run.status == "queued"

    store = InMemoryObjectStore()
    from app.runtime.scheduler import WorkerRuntime

    # Enqueue only (API-safe) then WorkerRuntime (worker-side Adapter)
    job = await AgentRunScheduler(pg_session).enqueue_node_run_only(confirmed.node_run_id)
    assert job
    queued = await pg_session.get(NodeRun, confirmed.node_run_id)
    assert queued is not None and queued.status == "queued"
    await WorkerRuntime(pg_session).process_one(confirmed.node_run_id)
    run2 = await pg_session.get(NodeRun, confirmed.node_run_id)
    assert run2 is not None and run2.status == "completed"
    art = await pg_session.get(Artifact, run2.result_artifact_id)
    assert art is not None
    assert art.byte_size > 8
    assert len(art.content_hash) == 64
    assert not art.object_key.startswith("https://")

    exp = await build_project_export(
        pg_session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[("1", "Opening")],
        store=store,
        try_ffmpeg=True,
    )
    assert exp.timeline_hash
    assert exp.srt_hash
    assert exp.package_hash
    assert exp.export_item_count >= 1
    assert exp.source_artifact_ids
    assert exp.export_id


@pytest.mark.asyncio
async def test_ten_shot_p0_and_subtitle_rework(pg_session: AsyncSession) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"s4-{suffix}@example.com",
        display_name="S4",
        password_hash=hash_password("password123"),
    )
    pg_session.add(user)
    await pg_session.flush()
    org = Organization(name=f"S4Org-{suffix}")
    pg_session.add(org)
    await pg_session.flush()
    pg_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    from app.access.projects import ProjectService

    await set_rls_context(pg_session, user_id=user.id, organization_id=org.id)
    project = await ProjectService(pg_session).create_project(
        organization_id=org.id, name=f"S4-{suffix}", aspect_ratio="9:16", actor=user
    )
    await pg_session.commit()
    await set_rls_context(
        pg_session,
        user_id=user.id,
        organization_id=org.id,
        project_id=project.id,
    )
    from app.execution.shot_p0 import set_shot_lock

    shots = await produce_shots_p0(
        pg_session, project_id=project.id, user_id=user.id, n=10
    )
    assert len(shots) == 10
    assert all(s.face_checked and s.continuity_checked for s in shots)
    assert all(len(s.node_ids) == 9 for s in shots)
    assert all(s.face_score is not None and s.face_score >= 0.5 for s in shots)
    kf_before = shots[0].run_ids["keyframe"]
    await rework_subtitle_only_p0(
        pg_session,
        project_id=project.id,
        user_id=user.id,
        shot=shots[0],
        new_subtitle="neon rain street rework",
        budget=__import__("decimal").Decimal("100"),
    )
    assert shots[0].run_ids["keyframe"] == kf_before
    await set_shot_lock(
        pg_session,
        project_id=project.id,
        shot_id=shots[0].shot_id,
        user_id=user.id,
        locked=True,
    )
    await pg_session.commit()
    with pytest.raises(ValueError, match="locked"):
        await rework_subtitle_only_p0(
            pg_session,
            project_id=project.id,
            user_id=user.id,
            shot=shots[0],
            new_subtitle="Nope",
            budget=__import__("decimal").Decimal("100"),
        )


@pytest.mark.asyncio
async def test_rls_cross_project_denied_as_app_role() -> None:
    """Prove FORCE RLS: app role with wrong project GUC cannot read other project."""
    from sqlalchemy import create_engine

    sync = _url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
    eng = create_engine(sync)
    with eng.begin() as conn:
        # Ensure role exists (migration 0005)
        conn.execute(
            text(
                """
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dramaforge_app') THEN
                    CREATE ROLE dramaforge_app NOINHERIT LOGIN PASSWORD 'dramaforge_app';
                    GRANT USAGE ON SCHEMA public TO dramaforge_app;
                    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dramaforge_app;
                  END IF;
                END $$
                """
            )
        )
        # Seed two projects as owner (bypasses when not FORCE... but we FORCE)
        # Owner still subject to FORCE — set GUC for seed
        u1 = conn.execute(
            text(
                """
                INSERT INTO users (email, display_name, password_hash)
                VALUES (:e, 'A', 'x') RETURNING id
                """
            ),
            {"e": f"rls-a-{uuid4().hex[:6]}@example.com"},
        ).scalar_one()
        u2 = conn.execute(
            text(
                """
                INSERT INTO users (email, display_name, password_hash)
                VALUES (:e, 'B', 'x') RETURNING id
                """
            ),
            {"e": f"rls-b-{uuid4().hex[:6]}@example.com"},
        ).scalar_one()
        o1 = conn.execute(
            text("INSERT INTO organizations (name) VALUES (:n) RETURNING id"),
            {"n": f"O1-{uuid4().hex[:6]}"},
        ).scalar_one()
        o2 = conn.execute(
            text("INSERT INTO organizations (name) VALUES (:n) RETURNING id"),
            {"n": f"O2-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO organization_members (organization_id, user_id, role) VALUES (:o,:u,'owner')"
            ),
            {"o": o1, "u": u1},
        )
        conn.execute(
            text(
                "INSERT INTO organization_members (organization_id, user_id, role) VALUES (:o,:u,'owner')"
            ),
            {"o": o2, "u": u2},
        )
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u1)})
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(o1)},
        )
        p1 = conn.execute(
            text(
                """
                INSERT INTO projects (organization_id, name, aspect_ratio, budget_limit)
                VALUES (:o, :n, '9:16', 0) RETURNING id
                """
            ),
            {"o": o1, "n": f"P1-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (:p,:u,'owner')"
            ),
            {"p": p1, "u": u1},
        )
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u2)})
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(o2)},
        )
        p2 = conn.execute(
            text(
                """
                INSERT INTO projects (organization_id, name, aspect_ratio, budget_limit)
                VALUES (:o, :n, '9:16', 0) RETURNING id
                """
            ),
            {"o": o2, "n": f"P2-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role) VALUES (:p,:u,'owner')"
            ),
            {"p": p2, "u": u2},
        )
        # As user1 with project1 context, cannot see project2
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u1)})
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(o1)},
        )
        conn.execute(
            text("SELECT set_config('app.current_project_id', :v, true)"),
            {"v": str(p1)},
        )
        # Switch to app role if possible
        try:
            conn.execute(text("SET LOCAL ROLE dramaforge_app"))
        except Exception:
            pytest.skip("dramaforge_app role not available")
        # Re-set GUC after role switch
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u1)})
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(o1)},
        )
        conn.execute(
            text("SELECT set_config('app.current_project_id', :v, true)"),
            {"v": str(p1)},
        )
        visible = conn.execute(
            text("SELECT id FROM projects WHERE id = :p"), {"p": p2}
        ).fetchall()
        assert visible == [], "cross-project row must be invisible under wrong GUC"
        own = conn.execute(
            text("SELECT id FROM projects WHERE id = :p"), {"p": p1}
        ).fetchall()
        assert len(own) == 1, "own project must remain visible under matching GUC"
        assert own[0][0] == p1
    eng.dispose()
