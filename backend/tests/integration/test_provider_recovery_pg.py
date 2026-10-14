"""Periodic Provider recovery under real PostgreSQL RLS and overlapping claims.

Uses the existing disposable-database integration harness; never run against an
application database. Queue admission is in memory and no Provider is invoked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.events.models import OutboxEvent
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.production.models import GraphVersion, ProductionGraph
from app.shared.db import (
    list_resumable_provider_node_run_rls_scopes,
    set_node_run_rls_context,
    set_rls_context,
)
from app.workers import jobs
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_provider_recovery import Queue


async def _seed(session, *, first_id, count, age=timedelta(hours=2), remote=True):
    user = User(email=f"provider-recovery-{uuid4()}@example.com", display_name="Owner",
                password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Recovery")
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="Recovery", stage="draft",
                      aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.flush()
    graph = ProductionGraph(
        project_id=project.id, scope_type="project", scope_entity_id=project.id,
        template_key="recovery-test", created_by=user.id,
    )
    session.add(graph)
    await session.flush()
    version = GraphVersion(graph_id=graph.id, version_number=1, definition_hash="a" * 64)
    session.add(version)
    await session.flush()
    node = GraphNode(
        graph_version_id=version.id, node_key="video", node_type="video", display_name="Video",
    )
    session.add(node)
    await session.flush()
    old = datetime.now(UTC) - age
    ids = []
    for number in range(count):
        run = NodeRun(
            id=UUID(int=first_id + number), project_id=project.id, graph_version_id=version.id,
            graph_node_id=node.id, attempt_no=number + 1, idempotency_key=f"recovery:{number}",
            input_hash="b" * 64, status="running", created_by=user.id,
            input_snapshot={"source_commit": "historical-release"}, started_at=old, created_at=old,
        )
        session.add(run)
        await session.flush()
        session.add(ProviderOperation(
            node_run_id=run.id, actual_provider="test", actual_model="test-video",
            operation_kind="video", request_fingerprint="c" * 64,
            execution_path_version="unified-v1",
            status="submitted" if remote else "submission_started",
            provider_operation_id=f"remote-{run.id}" if remote else None,
            created_at=old, submitted_at=old if remote else None,
        ))
        ids.append(run.id)
    await session.commit()
    return user, project, ids


@pytest.mark.asyncio
async def test_periodic_recovery_rls_paging_locks_and_worker_lease(monkeypatch):
    dbname = f"dramaforge_provider_recovery_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin = create_async_engine(_async_url(dbname))
    # Session-level role survives commits, unlike SET LOCAL ROLE. Each worker
    # transaction must still reapply the persisted owner's SET LOCAL app.*.
    app = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin_factory = async_sessionmaker(admin, expire_on_commit=False)
        factory = async_sessionmaker(app, expire_on_commit=False)
        async with admin_factory() as session:
            user, project, ids = await _seed(session, first_id=100, count=120)
            _, foreign_project, foreign_ids = await _seed(session, first_id=1000, count=1)
            _, _, fresh_ids = await _seed(session, first_id=1, count=1, age=timedelta(minutes=1))
            _, _, unknown_ids = await _seed(session, first_id=2, count=1, remote=False)
            signature = "app.resumable_provider_node_run_contexts(integer,text,uuid,timestamptz)"
            acl = (await session.execute(text(
                "SELECT p.prosecdef, p.proowner::regrole::text AS owner, p.proconfig, "
                "EXISTS (SELECT 1 FROM aclexplode(p.proacl) a "
                "WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_execute "
                "FROM pg_proc p WHERE p.oid = CAST(:signature AS regprocedure)"
            ), {"signature": signature})).one()
            assert acl.prosecdef is True
            assert acl.owner == "dramaforge_worker_resolver"
            assert acl.public_execute is False
            assert "search_path=public, pg_temp" in acl.proconfig

        async with factory() as session:
            assert await session.scalar(text("SELECT current_user")) == "dramaforge_app"
            assert list(await session.scalars(select(NodeRun.id))) == []
            # Caller cannot lift the 50-row cap or the 31-minute safety floor.
            scopes = await list_resumable_provider_node_run_rls_scopes(
                session, limit=500, stale_before=datetime.now(UTC) + timedelta(hours=1),
            )
            assert len(scopes) == 50
            assert fresh_ids[0] not in {run_id for run_id, _ in scopes}
            await set_rls_context(
                session, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id,
            )
            assert await session.get(NodeRun, foreign_ids[0]) is None
            assert len(list(await session.scalars(select(NodeRun.id)))) == 120
            await session.commit()
            assert list(await session.scalars(select(NodeRun.id))) == []

        queue = Queue()

        async def pool(*args, **kwargs):
            return queue

        monkeypatch.setattr("arq.create_pool", pool)
        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
        ctx = {}
        async with admin_factory() as lock:
            await lock.scalar(select(NodeRun).where(NodeRun.id == ids[0]).with_for_update())
            result = await jobs.recover_interrupted_provider_jobs(ctx)
            assert result["scanned"] == 50
            assert str(ids[0]) not in queue.admitted.values()
            await lock.rollback()
        # A locked head row must not pin the sweep, nor be lost after wrap.
        for _ in range(4):
            await jobs.recover_interrupted_provider_jobs(dict(ctx))
        expected = {str(run_id) for run_id in ids + foreign_ids}
        assert set(queue.admitted.values()) == expected
        await asyncio.gather(
            jobs.recover_interrupted_provider_jobs({}),
            jobs.recover_interrupted_provider_jobs({}),
        )
        async with admin_factory() as session:
            events = list(await session.scalars(select(OutboxEvent).where(
                OutboxEvent.topic == "node_run.enqueue",
            )))
            assert len(events) == 121
            assert (await session.get(NodeRun, fresh_ids[0])).status == "running"
            assert (await session.get(NodeRun, unknown_ids[0])).error_code == (
                "PROVIDER_SUBMISSION_UNKNOWN"
            )
            assert (await session.get(NodeRun, foreign_ids[0])).project_id == foreign_project.id
            assert all(event.payload.get("dispatch_generation") == "" for event in events)

        entered = asyncio.Event()
        calls = []

        async def poll(*args, **kwargs):
            calls.append(kwargs["node_run_id"])
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("app.execution.product_path.execute_media_node_run", poll)
        active = asyncio.create_task(jobs.execute_node_run({}, str(ids[0])))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            duplicate = await jobs.execute_node_run({}, str(ids[0]))
            assert duplicate["status"] == "already_claimed"
            calls_before = len(queue.calls)
            await jobs.recover_interrupted_provider_jobs({})
            assert all(run_id != str(ids[0]) for _, run_id in queue.calls[calls_before:])
            assert calls == [ids[0]]
        finally:
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
        # A recent task may have cooperatively yielded, then received cancellation.
        # NULL started_at is a released lease, not a fallback to its recent creation.
        released_id = fresh_ids[0]
        async with factory() as session:
            await set_node_run_rls_context(session, node_run_id=released_id)
            run = await session.get(NodeRun, released_id)
            run.status = "cancel_requested"
            run.cancellation_requested_at = datetime.now(UTC)
            run.started_at = None
            await session.commit()
        entered.clear()
        resumed = asyncio.create_task(jobs.execute_node_run({}, str(released_id)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            duplicate = await jobs.execute_node_run({}, str(released_id))
            assert duplicate["status"] == "already_claimed"
            assert calls == [ids[0], released_id]
            async with factory() as session:
                assert list(await session.scalars(select(NodeRun.id))) == []
                await set_node_run_rls_context(session, node_run_id=released_id)
                run = await session.get(NodeRun, released_id)
                assert run.status == "cancel_requested"
                assert run.started_at is not None
                assert run.cancellation_requested_at is not None
        finally:
            resumed.cancel()
            with pytest.raises(asyncio.CancelledError):
                await resumed
    finally:
        await app.dispose()
        await admin.dispose()
        await _drop_database(dbname)
