"""Bounded persisted Provider recovery; SQLite facts + an in-memory Arq boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.events.models import OutboxEvent
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.runtime import provider_recovery
from app.shared.base import Base
from app.workers import heavy, jobs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Queue:
    """Arq's stable-id admission boundary, not a fake recovery/scheduler."""

    def __init__(self):
        self.admitted = {}
        self.calls = []

    async def enqueue_job(self, function, *args, _job_id, _queue_name):
        self.calls.append((_job_id, args[0]))
        if _job_id in self.admitted:
            return None
        self.admitted[_job_id] = args[0]
        return SimpleNamespace(job_id=_job_id)

    async def close(self):
        pass


@pytest.fixture
async def recovery(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    queue = Queue()

    async def pool(*args, **kwargs):
        return queue

    monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
    monkeypatch.setattr(provider_recovery, "get_session_factory", lambda: factory)
    monkeypatch.setattr("arq.create_pool", pool)
    async with factory() as session:
        user = User(
            email=f"recovery-{uuid4()}@example.com", display_name="Owner", password_hash="x",
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(owner_user_id=user.id, name="Recovery")
        session.add(workspace)
        await session.flush()
        project = Project(workspace_id=workspace.id, name="Recovery", stage="draft",
                          aspect_ratio="16:9", budget_limit=0)
        session.add(project)
        await session.flush()
        node = GraphNode(
            graph_version_id=uuid4(), node_key="video", node_type="video", display_name="Video",
        )
        session.add(node)
        await session.commit()
        env = SimpleNamespace(
            factory=factory, queue=queue, project=project, user=user, node=node,
        )
    try:
        yield env
    finally:
        await engine.dispose()


async def seed(env, count=1, *, start=1, age=timedelta(hours=2), remote=True):
    now = datetime.now(UTC) - age
    ids = []
    async with env.factory() as session:
        for number in range(start, start + count):
            run = NodeRun(
                id=UUID(int=number), project_id=env.project.id,
                graph_version_id=env.node.graph_version_id, graph_node_id=env.node.id,
                attempt_no=number, idempotency_key=f"recovery:{number}", input_hash="a" * 64,
                status="running", input_snapshot={"source_commit": "previous-release"},
                created_by=env.user.id, started_at=now, created_at=now,
            )
            operation = ProviderOperation(
                node_run_id=run.id, operation_kind="video", actual_provider="test",
                actual_model="test-video", request_fingerprint="b" * 64,
                execution_path_version="unified-v1",
                status="submitted" if remote else "submission_started",
                provider_operation_id=f"remote-{number}" if remote else None,
                created_at=now, submitted_at=now if remote else None,
            )
            session.add_all([run, operation])
            ids.append(run.id)
        await session.commit()
    return ids


async def test_periodic_recovery_reaches_120_interrupted_tasks_in_bounded_batches(recovery):
    ids = await seed(recovery, 120)
    ctx = {"redis": recovery.queue}
    await heavy.WorkerSettings.on_startup(ctx)
    assert len(recovery.queue.admitted) == 50
    # The runtime core and startup entry share the same paging implementation.
    await provider_recovery.recover_interrupted_provider_jobs(dict(ctx))
    assert len(recovery.queue.admitted) == 100
    await provider_recovery.recover_interrupted_provider_jobs(dict(ctx))
    assert set(recovery.queue.admitted.values()) == {str(run_id) for run_id in ids}
    assert len(recovery.queue.admitted) == 120
    async with recovery.factory() as session:
        events = (await session.scalars(select(OutboxEvent))).all()
        assert len(events) == 120


async def test_active_resume_lease_blocks_another_job_and_recovery(recovery, monkeypatch):
    import asyncio

    (run_id,) = await seed(recovery)
    entered = asyncio.Event()
    calls = []

    async def poll_existing(*args, **kwargs):
        calls.append(kwargs["node_run_id"])
        if len(calls) > 1:
            raise AssertionError("duplicate polling of an active remote task")
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.execution.product_path.execute_media_node_run", poll_existing)
    first = asyncio.create_task(jobs.execute_node_run({}, str(run_id)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = await jobs.execute_node_run({}, str(run_id))
        assert second == {"status": "already_claimed", "node_run_id": str(run_id)}
        await jobs.recover_interrupted_provider_jobs({})
        assert recovery.queue.admitted == {}
        async with recovery.factory() as session:
            run = await session.get(NodeRun, run_id)
            assert run.status == "running"
            assert run.error_code is None
        assert calls == [run_id]
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

async def test_rows_becoming_stale_behind_cursor_are_revisited_without_restart(
    recovery, monkeypatch,
):
    base = datetime.now(UTC)

    class Clock(datetime):
        current = base

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(jobs, "datetime", Clock)
    monkeypatch.setattr(provider_recovery, "datetime", Clock)
    (late_id,) = await seed(recovery, age=timedelta(minutes=1), remote=False)
    old_ids = await seed(recovery, 55, start=10)
    ctx = {}
    await heavy.WorkerSettings.on_startup(ctx)
    assert len(recovery.queue.admitted) == 50
    async with recovery.factory() as session:
        assert (await session.get(NodeRun, late_id)).status == "running"
    # This row was not eligible at startup, and its key is behind the cursor.
    Clock.current = base + timedelta(minutes=33)
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert set(recovery.queue.admitted.values()) == {str(run_id) for run_id in old_ids}
    async with recovery.factory() as session:
        run = await session.get(NodeRun, late_id)
        operation = await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == late_id)
        )
        assert (run.status, run.error_code) == ("failed", "PROVIDER_SUBMISSION_UNKNOWN")
        assert operation.status == "unknown_submission"
        assert operation.provider_operation_id is None
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert str(late_id) not in recovery.queue.admitted.values()

async def test_overlap_uses_one_outbox_and_job_without_resetting_cancellation(
    recovery, monkeypatch,
):
    import asyncio

    (run_id,) = await seed(recovery)
    cancelled_at = datetime.now(UTC) - timedelta(hours=1)
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        run.status = "cancel_requested"
        run.cancellation_requested_at = cancelled_at
        run.input_snapshot = {"source_commit": "old", "dispatch_generation": "explicit-existing"}
        run.error_code = "PROVIDER_TASK_PENDING"
        run.error_summary = "keep this evidence"
        await session.commit()
    admitted = asyncio.Event()
    release = asyncio.Event()
    original = recovery.queue.enqueue_job

    async def enqueue(*args, **kwargs):
        job = await original(*args, **kwargs)
        admitted.set()
        await release.wait()
        return job

    monkeypatch.setattr(recovery.queue, "enqueue_job", enqueue)
    ctx = {}
    first = asyncio.create_task(jobs.recover_interrupted_provider_jobs(ctx))
    sibling = None
    try:
        await asyncio.wait_for(admitted.wait(), timeout=2)
        assert (await jobs.recover_interrupted_provider_jobs(dict(ctx)))["scanned"] == 0
        # A different worker has a different in-process cursor/overlap guard.
        sibling = asyncio.create_task(jobs.recover_interrupted_provider_jobs({}))
        release.set()
        await asyncio.gather(first, sibling)
    finally:
        release.set()
        await first
        if sibling is not None:
            await sibling
    await jobs.recover_interrupted_provider_jobs({})
    assert len(recovery.queue.admitted) == 1
    assert len({job_id for job_id, _ in recovery.queue.calls}) == 1
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        assert run.status == "cancel_requested"
        assert run.cancellation_requested_at.replace(tzinfo=UTC) == cancelled_at
        assert run.input_snapshot == {
            "source_commit": "old", "dispatch_generation": "explicit-existing",
        }
        assert (run.error_code, run.error_summary) == (
            "PROVIDER_TASK_PENDING", "keep this evidence",
        )
        assert len((await session.scalars(select(OutboxEvent))).all()) == 1


async def test_enqueue_failure_does_not_fail_remote_task_or_starve_siblings(recovery, monkeypatch):
    first, second = await seed(recovery, 2)
    original = recovery.queue.enqueue_job

    async def unavailable(function, *args, **kwargs):
        if args[0] == str(first):
            raise ConnectionError("isolated queue outage")
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(recovery.queue, "enqueue_job", unavailable)
    ctx = {}
    result = await jobs.recover_interrupted_provider_jobs(ctx)
    assert (result["failed"], result["resumed"]) == (1, 1)
    assert list(recovery.queue.admitted.values()) == [str(second)]
    async with recovery.factory() as session:
        run = await session.get(NodeRun, first)
        assert (run.status, run.error_code, run.input_snapshot) == (
            "running", None, {"source_commit": "previous-release"},
        )
        # Commit-before-enqueue survives; no stranded queued transition is needed.
        assert len((await session.scalars(select(OutboxEvent))).all()) == 2
    monkeypatch.setattr(recovery.queue, "enqueue_job", original)
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert set(recovery.queue.admitted.values()) == {str(first), str(second)}
    async with recovery.factory() as session:
        assert len((await session.scalars(select(OutboxEvent))).all()) == 2


async def test_time_bound_advances_only_past_attempted_row_and_retries_after_wrap(
    recovery, monkeypatch,
):
    import asyncio

    first, second = await seed(recovery, 2)
    original = recovery.queue.enqueue_job
    entered = []

    async def slow(function, *args, **kwargs):
        entered.append(args[0])
        await asyncio.Event().wait()

    monkeypatch.setattr(recovery.queue, "enqueue_job", slow)
    monkeypatch.setattr(provider_recovery, "PROVIDER_RECOVERY_TIMEOUT_SECONDS", 0.25)
    ctx = {}
    result = await jobs.recover_interrupted_provider_jobs(ctx)
    assert result["timed_out"] == 1
    assert entered == [str(first)]
    monkeypatch.setattr(recovery.queue, "enqueue_job", original)
    monkeypatch.setattr(provider_recovery, "PROVIDER_RECOVERY_TIMEOUT_SECONDS", 20)
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert list(recovery.queue.admitted.values()) == [str(second)]
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert set(recovery.queue.admitted.values()) == {str(first), str(second)}
    async with recovery.factory() as session:
        assert len((await session.scalars(select(OutboxEvent))).all()) == 2

async def test_remote_identity_resumes_interrupted_download_with_zero_create(recovery, monkeypatch):
    import asyncio
    import hashlib
    from io import BytesIO
    from unittest.mock import AsyncMock

    from app.execution.models import Artifact
    from app.providers.execution_identity import ExecutionIdentitySnapshot
    from app.providers.runtime import PollResult, ProviderResumeToken, ProviderRuntimeResolver
    from PIL import Image

    (run_id,) = await seed(recovery)
    identity = ExecutionIdentitySnapshot(
        resolved_model="test/image", resolution_source="project_snapshot",
        provider_model_binding_id=uuid4(), catalog_entry_id=uuid4(), model_revision="r1",
        manifest_hash="c" * 64, invoke_model_value="image", connection_id=uuid4(),
        connection_revision_id=uuid4(), credential_revision_id=uuid4(),
        capability="image.generate", mode_id="text-to-image", request_fingerprint="b" * 64,
    )
    resume = ProviderResumeToken(
        provider_type="test", protocol_profile="test-v1", remote_task_id="remote-1",
    )
    async with recovery.factory() as session:
        node = await session.get(GraphNode, recovery.node.id)
        node.node_type = "keyframe"
        node.node_key = "keyframe"
        run = await session.get(NodeRun, run_id)
        run.input_snapshot = {"execution_identity": identity.model_dump(mode="json")}
        operation = await session.scalar(select(ProviderOperation))
        operation.selection_plan = {"execution_identity": identity.model_dump(mode="json")}
        operation.request_summary = dict(operation.selection_plan)
        operation.resume_token = resume.model_dump(mode="json")
        operation_id = operation.id
        await session.commit()
    runtime = SimpleNamespace(
        poll_video=AsyncMock(return_value=PollResult(
            status="succeeded", artifact_uri="https://unit.invalid/result",
        )),
        fetch_cost=AsyncMock(return_value=SimpleNamespace(amount=None, cost_status="not_reported")),
        submit_image=AsyncMock(side_effect=AssertionError("must not create")),
        submit_video=AsyncMock(side_effect=AssertionError("must not create")),
    )
    resolver = AsyncMock(return_value=runtime)
    monkeypatch.setattr(ProviderRuntimeResolver, "resume_runtime_for_identity", resolver)
    prepare = AsyncMock(side_effect=AssertionError("must not recompile/resubmit"))
    monkeypatch.setattr("app.execution.provider_execution.prepare_media_submission", prepare)
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    media = buffer.getvalue()
    downloads = []

    async def download(**kwargs):
        downloads.append(kwargs["remote"])
        if len(downloads) == 1:
            raise asyncio.CancelledError()  # process dies during local download, not create
        return media

    async def store(**kwargs):
        return SimpleNamespace(
            object_key=kwargs["object_key"],
            content_hash=hashlib.sha256(kwargs["data"]).hexdigest(),
            mime_type=kwargs["mime_type"], byte_size=len(kwargs["data"]),
        )

    monkeypatch.setattr("app.execution.provider_execution._resolve_media_bytes", download)
    monkeypatch.setattr(
        "app.execution.product_path.get_object_store", lambda: SimpleNamespace(put_bytes=store),
    )
    ctx = {}
    await jobs.recover_interrupted_provider_jobs(ctx)
    with pytest.raises(asyncio.CancelledError):
        await jobs.execute_node_run({}, str(run_id))
    async with recovery.factory() as session:
        assert (await session.get(NodeRun, run_id)).status == "running"
        interrupted_operation = await session.get(ProviderOperation, operation_id)
        assert interrupted_operation.provider_operation_id == "remote-1"

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(minutes=32)

    monkeypatch.setattr(jobs, "datetime", Clock)
    monkeypatch.setattr(provider_recovery, "datetime", Clock)
    recovery.queue.admitted.clear()  # expired/lost queue delivery after the interrupted attempt
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    result = await jobs.execute_node_run({}, str(run_id))
    assert result["status"] == "completed"
    replay = await jobs.execute_node_run({}, str(run_id))
    assert replay["artifact_id"] == result["artifact_id"]
    await jobs.recover_interrupted_provider_jobs(dict(ctx))
    assert downloads == ["remote-1", "remote-1"]
    assert runtime.poll_video.await_count == 2
    assert all(call.args[0] == resume for call in runtime.poll_video.await_args_list)
    assert all(call.kwargs["identity"] == identity for call in resolver.await_args_list)
    runtime.submit_image.assert_not_awaited()
    runtime.submit_video.assert_not_awaited()
    prepare.assert_not_awaited()
    assert len({job_id for job_id, _ in recovery.queue.calls}) == 1
    async with recovery.factory() as session:
        assert len((await session.scalars(select(OutboxEvent))).all()) == 1
        assert len((await session.scalars(select(ProviderOperation))).all()) == 1
        artifact = (await session.scalars(select(Artifact))).one()
        assert artifact.produced_by_run_id == run_id
        assert artifact.content_hash == hashlib.sha256(media).hexdigest()


def test_recovery_bounds_outlive_heavy_attempt_and_arq_result_retention():
    from app.shared.rls_scopes import PROVIDER_RECOVERY_LEASE

    assert PROVIDER_RECOVERY_LEASE.total_seconds() >= (
        heavy.WorkerSettings.job_timeout + max(60, heavy.WorkerSettings.keep_result)
    )
    from app.workers import dispatcher

    assert heavy.WorkerSettings.on_startup is jobs.recover_interrupted_provider_jobs
    assert not getattr(heavy.WorkerSettings, "cron_jobs", [])
    assert provider_recovery.PROVIDER_RECOVERY_BATCH_SIZE == 50
    assert 0 < provider_recovery.PROVIDER_RECOVERY_TIMEOUT_SECONDS < (
        dispatcher.PROVIDER_RECOVERY_POLL_SECONDS
    )
    assert dispatcher.PROVIDER_RECOVERY_POLL_SECONDS == 60


async def test_dispatcher_recovery_bypasses_fifty_jobs_and_a_busy_single_heavy_slot(
    recovery, monkeypatch,
):
    import asyncio
    from unittest.mock import AsyncMock

    from app.workers import dispatcher
    from arq.worker import Worker

    ids = await seed(recovery, 120)
    await heavy.WorkerSettings.on_startup({})
    assert len(recovery.queue.admitted) == 50
    prefix = dict(recovery.queue.admitted)
    media_started = asyncio.Event()
    dispatch_started = asyncio.Event()
    tail_admitted = asyncio.Event()

    async def long_media(*args, **kwargs):
        media_started.set()
        await asyncio.Event().wait()

    async def blocked_outbox(*, worker_id):
        dispatch_started.set()
        await asyncio.Event().wait()

    enqueue = recovery.queue.enqueue_job

    async def observe_enqueue(*args, **kwargs):
        result = await enqueue(*args, **kwargs)
        if len(recovery.queue.admitted) == 120:
            tail_admitted.set()
        return result

    monkeypatch.setattr("app.execution.product_path.execute_media_node_run", long_media)
    monkeypatch.setattr(dispatcher, "dispatch_once", blocked_outbox)
    monkeypatch.setattr(dispatcher, "PROVIDER_RECOVERY_POLL_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(recovery.queue, "enqueue_job", observe_enqueue)
    # Use Arq's real admission gate, not a hand-invoked recovery cron coroutine.
    worker = Worker(
        functions=heavy.WorkerSettings.functions,
        queue_name=heavy.WorkerSettings.queue_name,
        max_jobs=1,
        redis_pool=recovery.queue,
        handle_signals=False,
    )
    worker.job_counter = 1
    start_jobs = AsyncMock()
    monkeypatch.setattr(worker, "start_jobs", start_jobs)
    monkeypatch.setattr(worker, "heart_beat", AsyncMock())
    media = asyncio.create_task(jobs.execute_node_run({}, str(ids[0])))
    resident = None
    try:
        await asyncio.wait_for(media_started.wait(), timeout=2)
        await worker._poll_iteration()
        start_jobs.assert_not_awaited()
        assert not media.done()
        resident = asyncio.create_task(dispatcher.run_forever())
        await asyncio.wait_for(dispatch_started.wait(), timeout=2)
        await asyncio.wait_for(tail_admitted.wait(), timeout=5)
        assert not media.done()
        assert worker.job_counter == worker.max_jobs == 1
        assert all(recovery.queue.admitted[key] == value for key, value in prefix.items())
        assert set(recovery.queue.admitted.values()) == {str(run_id) for run_id in ids}
    finally:
        tasks = [media] + ([resident] if resident is not None else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_poll_timeout_releases_lease_then_cancel_retries_same_remote_id(
    recovery, monkeypatch,
):
    from unittest.mock import AsyncMock

    from app.execution import provider_execution
    from app.providers.execution_identity import ExecutionIdentitySnapshot
    from app.providers.generation_service import GenerationService
    from app.providers.runtime import (
        CancelResult,
        PollResult,
        ProviderResumeToken,
        ProviderRuntimeResolver,
    )
    from arq import Retry

    # A recent created_at must not be mistaken for an active started_at lease.
    (run_id,) = await seed(recovery, age=timedelta(seconds=10))
    identity = ExecutionIdentitySnapshot(
        resolved_model="test/image", resolution_source="project_snapshot",
        provider_model_binding_id=uuid4(), catalog_entry_id=uuid4(), model_revision="r1",
        manifest_hash="c" * 64, invoke_model_value="image", connection_id=uuid4(),
        connection_revision_id=uuid4(), credential_revision_id=uuid4(),
        capability="image.generate", mode_id="text-to-image", request_fingerprint="b" * 64,
    )
    resume = ProviderResumeToken(
        provider_type="test", protocol_profile="test-v1", remote_task_id="remote-1",
    )
    async with recovery.factory() as session:
        node = await session.get(GraphNode, recovery.node.id)
        node.node_type = node.node_key = "keyframe"
        run = await session.get(NodeRun, run_id)
        run.status = "queued"
        snapshot = {
            "execution_identity": identity.model_dump(mode="json"),
            "dispatch_generation": "original-attempt",
        }
        run.input_snapshot = snapshot
        operation = await session.scalar(select(ProviderOperation))
        operation.selection_plan = {"execution_identity": identity.model_dump(mode="json")}
        operation.request_summary = dict(operation.selection_plan)
        operation.resume_token = resume.model_dump(mode="json")
        operation_id = operation.id
        await session.commit()

    clock = SimpleNamespace(seconds=0)
    clock.time = lambda: clock.seconds

    async def still_pending(token):
        assert token == resume
        clock.seconds += 121  # Cross the real 120s image polling budget, without sleeping.
        return PollResult(status="running")

    runtime = SimpleNamespace(
        poll_video=AsyncMock(side_effect=still_pending),
        cancel_video=AsyncMock(return_value=CancelResult(status="cancelled")),
        submit_image=AsyncMock(side_effect=AssertionError("must not create")),
        submit_video=AsyncMock(side_effect=AssertionError("must not create")),
    )
    resolver = AsyncMock(return_value=runtime)
    monkeypatch.setattr(ProviderRuntimeResolver, "resume_runtime_for_identity", resolver)
    prepare = AsyncMock(side_effect=AssertionError("must not compile/resubmit"))
    monkeypatch.setattr(provider_execution, "prepare_media_submission", prepare)
    # Replace only this module's clock access, never asyncio's global event loop.
    monkeypatch.setattr(provider_execution, "asyncio", SimpleNamespace(
        get_running_loop=lambda: clock, sleep=AsyncMock(),
    ))
    monkeypatch.setattr("app.execution.product_path.get_object_store", lambda: SimpleNamespace())
    with pytest.raises(Retry):
        await jobs.execute_node_run({"job_try": 1}, str(run_id))
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        operation = await session.get(ProviderOperation, operation_id)
        released_started_at = run.started_at
        assert run.status == "queued"
        assert operation.status == "timed_out"
        assert "120s" in operation.error_summary
        project = await session.get(Project, run.project_id)
        # The real cancellation method runs inside Arq's 5s retry window.
        await GenerationService(session, SimpleNamespace()).cancel_generation(
            project=project, operation_id=run_id,
        )
        await session.commit()
        assert run.status == "cancel_requested"

    result = await jobs.execute_node_run({"job_try": 2}, str(run_id))
    assert result == {"status": "cancelled", "node_run_id": str(run_id)}
    assert released_started_at is None
    runtime.poll_video.assert_awaited_once_with(resume)
    runtime.cancel_video.assert_awaited_once_with(resume)
    runtime.submit_image.assert_not_awaited()
    runtime.submit_video.assert_not_awaited()
    prepare.assert_not_awaited()
    assert resolver.await_count == 2
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        assert run.status == "cancelled"
        assert run.input_snapshot == snapshot
        operations = list(await session.scalars(select(ProviderOperation)))
        assert len(operations) == 1
        assert operations[0].id == operation_id
        assert operations[0].provider_operation_id == "remote-1"


async def test_dispatcher_retries_recovery_errors_without_blocking_outbox_and_joins_on_stop(
    monkeypatch,
):
    import asyncio

    from app.workers import dispatcher

    recovery_entered = asyncio.Event()
    recovery_stopped = asyncio.Event()
    outbox_progressed = asyncio.Event()
    contexts = []
    dispatches = 0

    async def recovery_tick(ctx):
        contexts.append(ctx)
        if len(contexts) == 1:
            raise ConnectionError("temporary discovery failure")
        recovery_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            recovery_stopped.set()

    async def outbox_tick(*, worker_id):
        nonlocal dispatches
        assert worker_id.startswith("outbox-dispatcher:")
        if recovery_entered.is_set():
            dispatches += 1
            if dispatches >= 2:
                outbox_progressed.set()
        return 1

    monkeypatch.setattr(dispatcher, "recover_interrupted_provider_jobs", recovery_tick)
    monkeypatch.setattr(dispatcher, "dispatch_once", outbox_tick)
    monkeypatch.setattr(dispatcher, "PROVIDER_RECOVERY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(dispatcher, "POLL_SECONDS", 0.01)
    resident = asyncio.create_task(dispatcher.run_forever())
    try:
        await asyncio.wait_for(outbox_progressed.wait(), timeout=2)
        assert len(contexts) == 2
        assert contexts[0] is contexts[1]
        assert not recovery_stopped.is_set()
    finally:
        resident.cancel()
        with pytest.raises(asyncio.CancelledError):
            await resident
    assert recovery_stopped.is_set()
    assert not any(
        task.get_name() in {"provider-recovery", "outbox-dispatch"}
        for task in asyncio.all_tasks()
    )
