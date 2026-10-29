"""Real Arq/Redis/PG slots: remote Retry-After must not hold local work behind it.

Only the Provider HTTP boundary is synthetic. Local prompt work persists a real
Artifact to MinIO. Queues, jobs, claims, durable due times and RLS are real.
"""

import asyncio
import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.minimax import MiniMaxRuntime
from app.providers.runtime import ProviderResumeToken, ProviderRuntimeResolver
from app.workers import jobs
from arq.connections import RedisSettings, create_pool
from arq.worker import Worker, func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from test_provider_recovery_pg import _seed


@pytest.mark.skipif(not os.environ.get("TEST_DIRECTOR_REDIS_URL"), reason="isolated Redis required")
@pytest.mark.parametrize("remote_count", [30, 100])
async def test_remote_wait_yields_real_worker_slots(remote_count, monkeypatch, record_property):
    dbname = f"dramaforge_queue_latency_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin = create_async_engine(_async_url(dbname))
    app = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}}
    )
    queue_name = f"dramaforge:latency:{uuid4().hex}"
    redis = await create_pool(RedisSettings.from_dsn(os.environ["TEST_DIRECTOR_REDIS_URL"]))
    worker = None
    artifact_key = None
    try:
        _alembic(dbname)
        admin_factory = async_sessionmaker(admin, expire_on_commit=False)
        factory = async_sessionmaker(app, expire_on_commit=False)
        identity = ExecutionIdentitySnapshot(
            resolved_model="minimax/synthetic-video",
            resolution_source="project_snapshot",
            provider_model_binding_id=uuid4(),
            catalog_entry_id=uuid4(),
            model_revision="synthetic-r1",
            manifest_hash="c" * 64,
            invoke_model_value="synthetic-video",
            connection_id=uuid4(),
            connection_revision_id=uuid4(),
            credential_revision_id=uuid4(),
            capability="video.generate",
            mode_id="text_to_video",
            request_fingerprint="b" * 64,
        ).model_dump(mode="json")
        async with admin_factory() as session:
            actor, project, remote_ids = await _seed(session, first_id=1, count=remote_count)
            remote_runs = list(await session.scalars(select(NodeRun)))
            for run in remote_runs:
                run.status, run.started_at = "queued", None
                run.input_snapshot = {"execution_identity": identity}
            for operation in (await session.scalars(select(ProviderOperation))).all():
                operation.actual_provider, operation.actual_model = "minimax", "synthetic-video"
                operation.protocol_profile = "minimax_cn_v1"
                operation.resume_token = ProviderResumeToken(
                    provider_type="minimax",
                    protocol_profile="minimax_cn_v1",
                    remote_task_id=operation.provider_operation_id,
                ).model_dump(mode="json")
                operation.selection_plan = {"execution_identity": identity}
                operation.request_summary = {"execution_identity": identity}
            local_node = GraphNode(
                graph_version_id=remote_runs[0].graph_version_id,
                node_key="prompt",
                node_type="prompt_compose",
                display_name="Local prompt",
            )
            session.add(local_node)
            await session.flush()
            local_run = NodeRun(
                project_id=project.id,
                graph_version_id=local_node.graph_version_id,
                graph_node_id=local_node.id,
                idempotency_key=uuid4().hex,
                input_hash="a" * 64,
                status="queued",
                input_snapshot={"prompt": "Synthetic local work"},
                created_by=actor.id,
            )
            session.add(local_run)
            await session.commit()
            local_id = str(local_run.id)

        polls = []

        async def remote_response(request):
            assert request.method == "GET", "existing tasks must never create again"
            polls.append(request.url.path.rsplit("/", 1)[-1])
            await asyncio.sleep(0.01)
            return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "wait"})

        runtime = MiniMaxRuntime(
            settings=Settings(minimax_enabled=True, minimax_api_key="synthetic-only"),
            host="https://controlled-provider.invalid",
            transport=httpx.MockTransport(remote_response),
        )

        async def resolve(self, **kwargs):
            assert kwargs["identity"].model_dump(mode="json") == identity
            return runtime

        monkeypatch.setattr(ProviderRuntimeResolver, "resume_runtime_for_identity", resolve)
        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
        active, peak = 0, 0
        local_started = None
        outcomes = []

        async def observed(ctx, node_run_id):
            nonlocal active, peak, local_started
            active += 1
            peak = max(peak, active)
            if node_run_id == local_id:
                local_started = time.perf_counter()
            try:
                outcome = await jobs.execute_node_run(ctx, node_run_id)
                outcomes.append(outcome["status"])
                return outcome
            finally:
                active -= 1

        for run_id in remote_ids:
            await redis.enqueue_job("execute_node_run", str(run_id), _queue_name=queue_name)
        local_enqueued = time.perf_counter()
        await redis.enqueue_job("execute_node_run", local_id, _queue_name=queue_name)
        worker = Worker(
            [func(observed, name="execute_node_run")],
            redis_pool=redis,
            queue_name=queue_name,
            burst=True,
            max_jobs=2,
            poll_delay=0.01,
            handle_signals=False,
            keep_result=0,
        )
        await asyncio.wait_for(worker.async_run(), timeout=30)
        assert local_started is not None
        wait_seconds = local_started - local_enqueued
        assert wait_seconds < 30 < 120
        assert peak == 2 and active == 0
        assert worker.jobs_failed == 0
        assert outcomes.count("provider_pending") == remote_count, outcomes
        assert len(polls) == len(set(polls)) == remote_count
        async with admin_factory() as session:
            local = await session.get(NodeRun, local_run.id)
            assert local.status == "completed" and local.result_artifact_id is not None
            artifact_key = (await session.get(Artifact, local.result_artifact_id)).object_key
            for run in await session.scalars(select(NodeRun).where(NodeRun.id.in_(remote_ids))):
                assert run.status == "queued" and run.started_at is None
                assert run.next_attempt_at > run.created_at
            operations = list(await session.scalars(select(ProviderOperation)))
            assert len(operations) == remote_count
            assert all(operation.provider_operation_id in polls for operation in operations)
        measurements = {
            "remote_tasks": remote_count,
            "worker_slots": 2,
            "peak_active": peak,
            "retry_after_seconds": 120,
            "local_enqueue_to_start_seconds": round(wait_seconds, 6),
            "extra_provider_create": 0,
        }
        record_property("queue_latency", json.dumps(measurements))
        print(json.dumps(measurements))
    finally:
        if worker is not None:
            await worker.close()
        else:
            await redis.aclose()
        if artifact_key:
            from app.storage.minio_store import get_object_store

            await get_object_store().delete_bytes(object_key=artifact_key)
        await app.dispose()
        await admin.dispose()
        await _drop_database(dbname)
