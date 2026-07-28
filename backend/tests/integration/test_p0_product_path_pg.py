"""P0 product path on real PostgreSQL: start → brief/plan → worker keyframe → export.

Requires Docker postgres. Captures evidence for Gate (async path, not request-thread spike).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.config import Settings
from app.creation.models import AgentRun, PlanningAuthorization
from app.creation.service import CreationService
from app.delivery.export_service import build_project_export
from app.events.models import OutboxEvent
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.shot_p0 import produce_shots_p0, rework_subtitle_only_p0
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.providers.fake import FakeOpenAIAdapter
from app.runtime.scheduler import WorkerRuntime
from app.shared.db import (
    list_pending_outbox_event_rls_scopes,
    list_queued_node_run_rls_scopes,
    resolve_node_run_rls_scope,
    set_rls_context,
)
from app.shared.enums import OutboxStatus
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def _pg_up() -> bool:
    """Fast connectivity probe — never hang collection for minutes."""
    try:
        import socket

        host, port = "127.0.0.1", 5432
        with socket.create_connection((host, port), timeout=1.0):
            pass
        from sqlalchemy import create_engine

        sync = _url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
        eng = create_engine(
            sync,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
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
async def test_agent_ten_shot_async_product_path(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This test drives its own WorkerRuntime. Keep all rows uncommitted so a
    # resident Arq worker sharing the local PostgreSQL instance cannot claim
    # these NodeRuns between the direct worker calls below.
    async def _flush_instead_of_commit() -> None:
        await pg_session.flush()

    monkeypatch.setattr(pg_session, "commit", _flush_instead_of_commit)

    suffix = uuid4().hex[:8]
    user = User(
        email=f"p0-{suffix}@example.com",
        display_name="P0",
        password_hash=hash_password("password123"),
    )
    pg_session.add(user)
    await pg_session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"P0Org-{suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    await pg_session.commit()

    await set_rls_context(
        pg_session, user_id=user.id, workspace_id=workspace.id
    )
    started = await CreationService(pg_session).start_project(
        workspace_id=workspace.id,
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
        workspace_id=workspace.id,
        project_id=started.project_id,
    )
    service = CreationService(pg_session)
    brief = await service.generate_brief_agent(
        project_id=started.project_id,
        actor=user,
        idea="A hero walks into neon rain and follows a dangerous clue.",
        authorize=True,
    )
    rev = await service.confirm_brief(
        project_id=started.project_id, revision_id=brief.id, actor=user
    )
    assert rev.status == "confirmed"
    plan = await service.generate_plan_agent(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=rev.id,
        authorize=True,
    )
    assert plan.source_agent_run_id is not None
    assert len(plan.plan["shots"]) == 10
    confirmed = await service.confirm_plan_and_materialize(
        project_id=started.project_id,
        plan_id=plan.id,
        actor=user,
    )
    assert len(confirmed.shot_ids) == 10
    assert len(confirmed.graph_version_ids) == 10
    assert len(confirmed.node_run_ids) == 10

    from app.execution.shot_p0 import SHOT_NODES
    from app.execution.shot_review import start_shot_nodes
    from app.production.models import GraphVersion

    versions = [
        await pg_session.get(GraphVersion, graph_version_id)
        for graph_version_id in confirmed.graph_version_ids
    ]
    assert all(version is not None for version in versions)
    for version in versions:
        assert version is not None
        graph_nodes = (
            await pg_session.execute(
                select(GraphNode).where(GraphNode.graph_version_id == version.id)
            )
        ).scalars().all()
        assert {node.node_key for node in graph_nodes} == set(SHOT_NODES)

    reset_object_store_for_tests()
    store = get_object_store()
    worker = WorkerRuntime(pg_session)
    async def run_current_project_nodes(node_run_ids: list[UUID]) -> None:
        """Keep this evidence run isolated from historical queued database work."""
        for node_run_id in node_run_ids:
            await set_rls_context(
                pg_session,
                user_id=user.id,
                project_id=started.project_id,
            )
            assert await worker.process_one(node_run_id)

    await run_current_project_nodes(confirmed.node_run_ids)
    queued_node_run_ids: list[UUID] = []
    for shot_id in confirmed.shot_ids:
        queued = await start_shot_nodes(
            pg_session,
            project_id=started.project_id,
            shot_id=shot_id,
            user_id=user.id,
        )
        assert len(queued) == len(SHOT_NODES) - 1
        queued_node_run_ids.extend(queued)
    await pg_session.commit()
    await run_current_project_nodes(queued_node_run_ids)

    runs = (
        await pg_session.execute(
            select(NodeRun).where(NodeRun.project_id == started.project_id)
        )
    ).scalars().all()
    artifacts = {
        artifact.id: artifact
        for artifact in (
            await pg_session.execute(
                select(Artifact).where(Artifact.project_id == started.project_id)
            )
        ).scalars().all()
    }
    done = {"completed", "cached", "completed_after_cancel"}
    artifact_ids: set[object] = set()
    object_keys: set[str] = set()
    for shot_id in confirmed.shot_ids:
        latest_by_key: dict[str, NodeRun] = {}
        for run in runs:
            snapshot = run.input_snapshot or {}
            if str(snapshot.get("shot_id")) != str(shot_id):
                continue
            key = str(snapshot.get("node_key") or "")
            if key and (
                key not in latest_by_key
                or run.attempt_no >= latest_by_key[key].attempt_no
            ):
                latest_by_key[key] = run
        assert set(latest_by_key) == set(SHOT_NODES)
        for key in SHOT_NODES:
            run = latest_by_key[key]
            assert run.status in done, (
                f"shot={shot_id} node={key} status={run.status} "
                f"error={run.error_code}:{run.error_summary}"
            )
            assert run.result_artifact_id is not None
            artifact = artifacts[run.result_artifact_id]
            assert artifact.produced_by_run_id == run.id
            assert await store.get_bytes(object_key=artifact.object_key)
            artifact_ids.add(artifact.id)
            object_keys.add(artifact.object_key)
    assert len(artifact_ids) == 10 * len(SHOT_NODES)
    assert len(object_keys) == 10 * len(SHOT_NODES)

    # store=None forces product default get_object_store() (same singleton Worker used)
    exp = await build_project_export(
        pg_session,
        project_id=started.project_id,
        requested_by=user.id,
        shot_subtitles=[(str(number), f"Shot {number}") for number in range(1, 11)],
        store=None,
        try_ffmpeg=True,
        require_approved=False,
    )
    assert exp.timeline_hash
    assert exp.srt_hash
    assert exp.package_hash
    assert exp.export_item_count >= 10
    assert exp.source_artifact_ids
    # With shared store + PNG frames, either real MP4 or explicit env error (not empty-store)
    assert exp.mp4_error != "FFMPEG_NO_READABLE_FRAMES" or not __import__("shutil").which(
        "ffmpeg"
    )


@pytest.mark.asyncio
async def test_agent_brief_plan_postgres_enum_contract(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.config as config_module
    import app.creation.service as creation_service_module

    settings = Settings(app_env="test", database_url=_url())
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        creation_service_module,
        "get_openai_adapter",
        lambda *, allow_live=False: FakeOpenAIAdapter(),
    )

    suffix = uuid4().hex[:8]
    user = User(
        email=f"agent-pg-{suffix}@example.com",
        display_name="Agent PG",
        password_hash=hash_password("password123"),
    )
    pg_session.add(user)
    await pg_session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"AgentPgOrg-{suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    await pg_session.commit()

    await set_rls_context(pg_session, user_id=user.id, workspace_id=workspace.id)
    service = CreationService(pg_session)
    started = await service.start_project(
        workspace_id=workspace.id,
        name=f"AgentPg-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="rainy night reunion",
    )
    await set_rls_context(
        pg_session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=started.project_id,
    )

    brief = await service.generate_brief_agent(
        project_id=started.project_id,
        actor=user,
        idea="rainy night reunion",
        authorize=True,
    )
    confirmed = await service.confirm_brief(
        project_id=started.project_id,
        revision_id=brief.id,
        actor=user,
    )
    plan = await service.generate_plan_agent(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=confirmed.id,
        authorize=True,
    )

    authorizations = (
        await pg_session.execute(
            select(PlanningAuthorization)
            .where(PlanningAuthorization.project_id == started.project_id)
            .order_by(PlanningAuthorization.created_at)
        )
    ).scalars().all()
    runs = (
        await pg_session.execute(
            select(AgentRun)
            .where(AgentRun.project_id == started.project_id)
            .order_by(AgentRun.created_at)
        )
    ).scalars().all()
    operations = (
        await pg_session.execute(
            select(ProviderOperation).where(
                ProviderOperation.agent_run_id.in_([run.id for run in runs])
            )
        )
    ).scalars().all()

    assert brief.source_kind == "agent"
    assert plan.source_agent_run_id is not None
    assert [row.authorized_operations for row in authorizations] == [
        ["draft_brief"],
        ["draft_plan"],
    ]
    assert [run.operation for run in runs] == ["draft_brief", "draft_plan"]
    assert all(run.status == "succeeded" for run in runs)
    assert len(operations) == 2
    assert all(operation.status == "succeeded" for operation in operations)


@pytest.mark.asyncio
async def test_cancelled_worker_keeps_durable_claim_and_blocks_duplicate_provider_call(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.access.projects import ProjectService
    from app.production.service import GraphService
    from app.providers.fake import FakeFluxAdapter

    class BlockingFluxAdapter(FakeFluxAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.create_attempts = 0
            self.never_returns = asyncio.Event()

        async def create(self, request: dict[str, object]) -> dict[str, object]:
            self.create_attempts += 1
            self.started.set()
            await self.never_returns.wait()
            return await super().create(request)

    suffix = uuid4().hex[:8]
    user = User(
        email=f"claim-{suffix}@example.com",
        display_name="Claim",
        password_hash=hash_password("password123"),
    )
    pg_session.add(user)
    await pg_session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"ClaimOrg-{suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    await set_rls_context(pg_session, user_id=user.id, workspace_id=workspace.id)
    project = await ProjectService(pg_session).create_project(
        workspace_id=workspace.id,
        name=f"ClaimProj-{suffix}",
        aspect_ratio="9:16",
        actor=user,
    )
    graph = await GraphService(pg_session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    pg_session.add(node)
    await pg_session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"claim:{suffix}",
        input_hash="c" * 64,
        status="queued",
        input_snapshot={"prompt": "atomic claim keyframe"},
        created_by=user.id,
    )
    pg_session.add(run)
    await pg_session.commit()

    adapter = BlockingFluxAdapter()
    monkeypatch.setattr(
        "app.providers.flux.get_flux_adapter",
        lambda *, allow_fake=False: adapter,
    )
    engine = create_async_engine(_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def consume() -> bool:
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=user.id,
                workspace_id=workspace.id,
                project_id=project.id,
            )
            return await WorkerRuntime(session).process_one(run.id)

    first = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(adapter.started.wait(), timeout=5)

        async with factory() as observer:
            await set_rls_context(
                observer,
                user_id=user.id,
                workspace_id=workspace.id,
                project_id=project.id,
            )
            observed = await observer.get(NodeRun, run.id)
            assert observed is not None
            assert observed.status == "running"

        assert await asyncio.wait_for(consume(), timeout=2) is False
        assert adapter.create_attempts == 1

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    finally:
        if not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        await engine.dispose()

    await pg_session.rollback()
    await set_rls_context(
        pg_session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )
    await pg_session.refresh(run)
    assert run.status == "running"
    artifacts = (
        await pg_session.execute(
            select(Artifact).where(Artifact.produced_by_run_id == run.id)
        )
    ).scalars().all()
    operations = (
        await pg_session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalars().all()
    assert adapter.create_attempts == 1
    assert len(adapter.calls) == 0
    assert artifacts == []
    assert operations == []


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
    workspace = Workspace(owner_user_id=user.id, name=f"S4Org-{suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    from app.access.projects import ProjectService

    await set_rls_context(pg_session, user_id=user.id, workspace_id=workspace.id)
    project = await ProjectService(pg_session).create_project(
        workspace_id=workspace.id, name=f"S4-{suffix}", aspect_ratio="9:16", actor=user
    )
    await pg_session.commit()
    await set_rls_context(
        pg_session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )
    from app.execution.shot_p0 import set_shot_lock

    store = get_object_store()
    shots = await produce_shots_p0(
        pg_session, project_id=project.id, user_id=user.id, n=10, store=store
    )
    assert len(shots) == 10
    assert all(s.face_checked and s.continuity_checked for s in shots)
    assert all(len(s.node_ids) == 9 for s in shots)
    # Two-source review: scores are real comparisons (not identity unit-vector);
    # generated keyframe vs canonical may score below 0.5 on hash embeddings.
    assert all(s.face_status is not None for s in shots)
    assert all(s.face_score is not None for s in shots)
    # Deliberate mismatch must not look like near-perfect identity
    bad = await produce_shots_p0(
        pg_session,
        project_id=project.id,
        user_id=user.id,
        n=1,
        store=store,
        mismatch_face_on_shot=1,
    )
    assert bad[0].face_status in {"blocked", "needs_human", "warning"} or (
        bad[0].face_score is not None and bad[0].face_score < 0.95
    )
    kf_before = shots[0].run_ids["keyframe"]
    await rework_subtitle_only_p0(
        pg_session,
        project_id=project.id,
        user_id=user.id,
        shot=shots[0],
        new_subtitle="neon rain street rework",
        budget=__import__("decimal").Decimal("100"),
        store=store,
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
            store=store,
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
                    GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO dramaforge_app;
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
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u1)})
        w1 = conn.execute(
            text(
                "INSERT INTO workspaces (owner_user_id, name) "
                "VALUES (:u, :n) RETURNING id"
            ),
            {"u": u1, "n": f"O1-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :v, true)"),
            {"v": str(w1)},
        )
        p1 = conn.execute(
            text(
                """
                INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit)
                VALUES (:o, :n, '9:16', 0) RETURNING id
                """
            ),
            {"o": w1, "n": f"P1-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u2)})
        w2 = conn.execute(
            text(
                "INSERT INTO workspaces (owner_user_id, name) "
                "VALUES (:u, :n) RETURNING id"
            ),
            {"u": u2, "n": f"O2-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :v, true)"),
            {"v": str(w2)},
        )
        p2 = conn.execute(
            text(
                """
                INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit)
                VALUES (:o, :n, '9:16', 0) RETURNING id
                """
            ),
            {"o": w2, "n": f"P2-{uuid4().hex[:6]}"},
        ).scalar_one()
        # As user1 with project1 context, cannot see project2
        conn.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(u1)})
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :v, true)"),
            {"v": str(w1)},
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
            text("SELECT set_config('app.current_workspace_id', :v, true)"),
            {"v": str(w1)},
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


@pytest.mark.asyncio
async def test_rls_same_owner_cross_workspace_denied_as_app_role() -> None:
    """An active workspace excludes another workspace owned by the same user."""
    from sqlalchemy import create_engine

    sync = _url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
    eng = create_engine(sync)
    with eng.begin() as conn:
        user_id = conn.execute(
            text(
                """
                INSERT INTO users (email, display_name, password_hash)
                VALUES (:email, 'Workspace owner', 'x') RETURNING id
                """
            ),
            {"email": f"rls-workspaces-{uuid4().hex[:6]}@example.com"},
        ).scalar_one()
        conn.execute(
            text("SELECT set_config('app.current_user_id', :value, true)"),
            {"value": str(user_id)},
        )
        workspace_a = conn.execute(
            text(
                "INSERT INTO workspaces (owner_user_id, name) "
                "VALUES (:owner, :name) RETURNING id"
            ),
            {"owner": user_id, "name": f"Workspace A-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :value, true)"),
            {"value": str(workspace_a)},
        )
        project_a = conn.execute(
            text(
                "INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit) "
                "VALUES (:workspace, :name, '9:16', 0) RETURNING id"
            ),
            {"workspace": workspace_a, "name": f"Project A-{uuid4().hex[:6]}"},
        ).scalar_one()
        workspace_b = conn.execute(
            text(
                "INSERT INTO workspaces (owner_user_id, name) "
                "VALUES (:owner, :name) RETURNING id"
            ),
            {"owner": user_id, "name": f"Workspace B-{uuid4().hex[:6]}"},
        ).scalar_one()
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :value, true)"),
            {"value": str(workspace_b)},
        )
        project_b = conn.execute(
            text(
                "INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit) "
                "VALUES (:workspace, :name, '9:16', 0) RETURNING id"
            ),
            {"workspace": workspace_b, "name": f"Project B-{uuid4().hex[:6]}"},
        ).scalar_one()
        credential_b = conn.execute(
            text(
                """
                INSERT INTO encrypted_provider_credentials
                  (workspace_id, provider, ciphertext, key_version)
                VALUES (:workspace, 'text', :ciphertext, 'test')
                RETURNING id
                """
            ),
            {"workspace": workspace_b, "ciphertext": "ciphertext-b"},
        ).scalar_one()
        # Select workspace A again before adding its credential. The credential
        # policy requires the selected workspace even while seeding as table owner.
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :value, true)"),
            {"value": str(workspace_a)},
        )
        credential_a = conn.execute(
            text(
                """
                INSERT INTO encrypted_provider_credentials
                  (workspace_id, provider, ciphertext, key_version)
                VALUES (:workspace, 'text', :ciphertext, 'test')
                RETURNING id
                """
            ),
            {"workspace": workspace_a, "ciphertext": "ciphertext-a"},
        ).scalar_one()

        conn.execute(text("SET LOCAL ROLE dramaforge_app"))
        conn.execute(
            text("SELECT set_config('app.current_user_id', :value, true)"),
            {"value": str(user_id)},
        )
        conn.execute(
            text("SELECT set_config('app.current_workspace_id', :value, true)"),
            {"value": str(workspace_a)},
        )
        conn.execute(text("SELECT set_config('app.current_project_id', '', true)"))

        assert conn.execute(
            text("SELECT id FROM projects WHERE id = :project_id"),
            {"project_id": project_a},
        ).scalar_one() == project_a
        assert conn.execute(
            text("SELECT id FROM projects WHERE id = :project_id"),
            {"project_id": project_b},
        ).fetchall() == []
        assert conn.execute(
            text(
                "SELECT id FROM encrypted_provider_credentials WHERE id = :credential_id"
            ),
            {"credential_id": credential_a},
        ).scalar_one() == credential_a
        assert conn.execute(
            text(
                "SELECT id FROM encrypted_provider_credentials WHERE id = :credential_id"
            ),
            {"credential_id": credential_b},
        ).fetchall() == []
    eng.dispose()


@pytest.mark.asyncio
async def test_worker_resolvers_use_workspace_owner_and_project_scope(
    pg_session: AsyncSession,
) -> None:
    """Worker scope comes from NodeRun -> Project -> Workspace, never created_by."""
    suffix = uuid4().hex[:8]
    owner = User(
        email=f"resolver-owner-{suffix}@example.com",
        display_name="Owner",
        password_hash="x",
    )
    creator = User(
        email=f"resolver-creator-{suffix}@example.com",
        display_name="Creator",
        password_hash="x",
    )
    pg_session.add_all([owner, creator])
    await pg_session.flush()
    workspace = Workspace(owner_user_id=owner.id, name=f"Resolver-{suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    await set_rls_context(pg_session, user_id=owner.id, workspace_id=workspace.id)
    project = await ProjectService(pg_session).create_project(
        workspace_id=workspace.id,
        name=f"Resolver-project-{suffix}",
        aspect_ratio="9:16",
        actor=owner,
    )
    graph = ProductionGraph(
        project_id=project.id,
        scope_type="episode",
        scope_entity_id=project.id,
        template_key="resolver-test",
        status="draft",
        created_by=owner.id,
    )
    pg_session.add(graph)
    await pg_session.flush()
    version = GraphVersion(
        graph_id=graph.id,
        version_number=1,
        status="draft",
        definition={"nodes": []},
        definition_hash=definition_hash({"nodes": []}),
    )
    pg_session.add(version)
    await pg_session.flush()
    node = GraphNode(
        graph_version_id=version.id,
        node_key="resolver",
        node_type="keyframe",
        display_name="Resolver",
        input_schema={},
        output_schema={},
        config={},
    )
    pg_session.add(node)
    await pg_session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"resolver-{suffix}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={},
        output_summary={},
        provider_cost=0,
        platform_cost=0,
        avoided_cost_estimate=0,
        created_by=creator.id,
    )
    pg_session.add(run)
    event = OutboxEvent(
        event_id=uuid4(),
        project_id=project.id,
        topic="resolver.test",
        schema_version=1,
        payload={"node_run_id": str(run.id)},
        status=OutboxStatus.PENDING.value,
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
    )
    pg_session.add(event)
    await pg_session.commit()

    run_scope = await resolve_node_run_rls_scope(pg_session, node_run_id=run.id)
    assert run_scope is not None
    assert run_scope.user_id == owner.id
    assert run_scope.user_id != creator.id
    assert run_scope.workspace_id == workspace.id
    assert run_scope.project_id == project.id

    queued = await list_queued_node_run_rls_scopes(
        pg_session, limit=10, project_id=project.id
    )
    assert [(run_id, scope.user_id) for run_id, scope in queued] == [(run.id, owner.id)]
    pending = await list_pending_outbox_event_rls_scopes(
        pg_session, limit=10, project_id=project.id
    )
    assert [(scope.event_id, scope.user_id) for scope in pending] == [
        (event.event_id, owner.id)
    ]
