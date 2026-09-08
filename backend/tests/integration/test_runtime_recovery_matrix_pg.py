"""R5 failure matrix against real PostgreSQL and the actual unified Worker.

Controlled plugin only: no paid Provider traffic. Assertions distinguish local
state, remote calls, frozen identity and Artifact/Shot lineage.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.access.models import Project
from app.assets.models import Episode, Scene, Shot
from app.execution.experiment_nodes import queue_branch_nodes
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.providers import registry as registry_module
from app.providers.generation_service import GenerationService
from app.providers.registry import ProviderPlugin, register_plugin
from app.providers.runtime import CancelResult, PollResult, ProviderResumeToken, SubmissionResult
from app.runtime.scheduler import NodeRunScheduler, WorkerRuntime
from app.shared.db import set_rls_context
from app.workers import jobs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import (
    _FAKE_MANIFEST,
    FAKE_PROFILE,
    FAKE_PROVIDER,
    _byok,
    _P5ImageCompiler,
    _P5Runtime,
    _P5VideoCompiler,
    _project,
    _seed_binding,
)
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        "cancelled",
        "late_success",
        "cancel_ack_lost",
        "submit_unknown",
        "rate_limit",
        "invalid_media",
        "download_failure",
        "missing_media",
        "raw_media",
        "queued_cancel",
    ],
)
async def test_cancel_restart_never_recreates_remote_task(
    pg_session,
    monkeypatch,
    outcome,
    record_property,
):
    _byok(monkeypatch)
    session = pg_session
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
    calls = {"create": 0, "poll": 0, "cancel": 0}
    polled_ids = []
    state = {"interrupt_poll": True}
    remote_id = f"r5-{uuid4().hex}"

    class Runtime(_P5Runtime):
        async def submit_image(self, request):
            calls["create"] += 1
            if outcome == "submit_unknown":
                raise asyncio.CancelledError()
            if outcome == "rate_limit" and calls["create"] == 1:
                return SubmissionResult(
                    status="failed",
                    error_code="PROVIDER_RATE_LIMITED",
                    error="429",
                    retry_after_seconds=7,
                    http_status=429,
                )
            return SubmissionResult(
                remote_task_id=remote_id,
                status="submitted",
                resume_token=ProviderResumeToken(
                    provider_type=FAKE_PROVIDER,
                    protocol_profile=FAKE_PROFILE,
                    remote_task_id=remote_id,
                    query_kind="task_id",
                ),
            )

        async def poll_video(self, resume):
            calls["poll"] += 1
            polled_ids.append(resume.remote_task_id)
            if state["interrupt_poll"] and outcome not in {
                "rate_limit",
                "invalid_media",
                "download_failure",
                "missing_media",
                "raw_media",
            }:
                state["interrupt_poll"] = False
                raise asyncio.CancelledError()
            uri = {
                "invalid_media": "data:image/png;base64,bm90IGFuIGltYWdl",
                "download_failure": "https://93.184.216.34/result.png",
                "missing_media": None,
                "raw_media": "totally-not-an-image",
            }.get(outcome, "fake://r5-result")
            return PollResult(status="succeeded", artifact_uri=uri)

        async def cancel_video(self, resume):
            assert resume.remote_task_id == remote_id
            calls["cancel"] += 1
            if outcome == "cancel_ack_lost":
                raise asyncio.CancelledError()
            return CancelResult(status="cancelled" if outcome == "cancelled" else "unsupported")

    runtime = Runtime()
    plugin = ProviderPlugin(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        display_name="R5 controlled",
        default_base_url="https://unified.example.com",
        implemented=True,
        settings_prefix=FAKE_PROVIDER,
        credential_provider_key=FAKE_PROVIDER,
        catalog_manifests=(_FAKE_MANIFEST,),
        runtime_factory=lambda **kw: runtime,
        compiler_factory=lambda: (_P5ImageCompiler(), _P5VideoCompiler()),
    )
    register_plugin(plugin)
    try:
        user, project_id, workspace_id = await _project(session)
        project = await session.get(Project, project_id)
        episode = Episode(project_id=project_id, episode_number=1, title="R5")
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id, scene_number=1, location_name="Studio", time_of_day="day"
        )
        session.add(scene)
        await session.flush()
        shot = Shot(
            project_id=project_id,
            scene_id=scene.id,
            shot_number=1,
            visual_description="portrait",
            duration_seconds=5,
            status="draft",
        )
        session.add(shot)
        await session.flush()
        model = f"r5-image-{uuid4().hex[:8]}"
        binding, connection = await _seed_binding(
            session,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user.id,
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=model,
            media_kind="image",
            purpose="keyframe",
            manifest={**_FAKE_MANIFEST, "model_id": model},
            invoke_model_value=model,
        )
        await session.commit()
        run_ids = await queue_branch_nodes(
            session,
            project_id=project_id,
            shot_id=shot.id,
            user_id=user.id,
            node_keys=["prompt", "keyframe"],
        )
        await session.commit()
        assert await WorkerRuntime(session).process_one(run_ids[0])
        await session.commit()
        if outcome == "queued_cancel":
            run = await session.get(NodeRun, run_ids[1])
            service = GenerationService(session, SimpleNamespace())
            await service.cancel_generation(project=project, operation_id=run.id)
            await session.commit()
            await service.cancel_generation(project=project, operation_id=run.id)
            result = await jobs.execute_node_run({}, str(run.id))
            assert result["status"] == "cancelled" and run.status == "cancelled"
            assert calls == {"create": 0, "poll": 0, "cancel": 0}
            return
        if outcome == "rate_limit":
            from arq import Retry

            with pytest.raises(Retry) as limited:
                await jobs.execute_node_run({}, str(run_ids[1]))
            assert limited.value.defer_score == 7000
            op = await session.scalar(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run_ids[1])
            )
            frozen = dict(op.selection_plan["execution_identity"])
            assert op.status == "rejected" and op.provider_operation_id is None
            binding.enabled = False
            await session.commit()
            result = await jobs.execute_node_run({}, str(run_ids[1]))
            assert result["status"] == "completed", result
            await session.refresh(op)
            assert op.selection_plan["execution_identity"] == frozen
            assert calls == {"create": 2, "poll": 1, "cancel": 0}
            return
        if outcome in {"invalid_media", "missing_media", "raw_media", "download_failure"}:
            if outcome == "download_failure":
                import httpx

                async def fail_download(**kwargs):
                    raise httpx.ReadTimeout("controlled download timeout")

                monkeypatch.setattr(
                    "app.execution.product_path._download_provider_media", fail_download
                )
            if outcome == "missing_media":
                import app.config as config

                settings = config.get_settings()
                monkeypatch.setattr(
                    config,
                    "get_settings",
                    lambda: settings.model_copy(update={"app_env": "development"}),
                )
            result = await jobs.execute_node_run({}, str(run_ids[1]))
            run = await session.get(NodeRun, run_ids[1], populate_existing=True)
            expected = (
                "PROVIDER_MEDIA_MISSING"
                if outcome == "missing_media"
                else "PROVIDER_MEDIA_DOWNLOAD_FAILED"
                if outcome == "download_failure"
                else "PROVIDER_MEDIA_INVALID"
            )
            assert result["status"] == "failed" and run.error_code == expected, result
            artifacts = list(
                (
                    await session.execute(
                        select(Artifact).where(Artifact.produced_by_run_id == run.id)
                    )
                ).scalars()
            )
            assert artifacts == []
            assert calls == {"create": 1, "poll": 1, "cancel": 0}
            return
        with pytest.raises(asyncio.CancelledError):
            await jobs.execute_node_run({}, str(run_ids[1]))
        await session.rollback()
        await set_rls_context(
            session, user_id=user.id, workspace_id=workspace_id, project_id=project_id
        )
        run = await session.get(NodeRun, run_ids[1], populate_existing=True)
        op = await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
        frozen = dict(op.selection_plan["execution_identity"])
        assert calls["create"] == 1
        if outcome == "submit_unknown":
            assert op.status == "submission_started" and op.provider_operation_id is None
            from datetime import UTC, datetime, timedelta

            # A fresh submission may belong to another live Worker. Do not
            # mark it unknown until the configured 30-minute job bound expires.
            await jobs.recover_interrupted_provider_jobs({})
            await session.refresh(run)
            assert run.status == "running"
            op.created_at = datetime.now(UTC) - timedelta(minutes=31)
            await session.commit()
            await jobs.recover_interrupted_provider_jobs({})
            await session.refresh(op)
            await session.refresh(run)
            assert run.status == "failed"
            assert op.status == "unknown_submission"
            assert run.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
            assert calls == {"create": 1, "poll": 0, "cancel": 0}
            return
        assert op.provider_operation_id == remote_id
        await GenerationService(session, SimpleNamespace()).cancel_generation(
            project=project, operation_id=run.id
        )
        await session.commit()
        # Changing the mutable binding cannot change a recovery's frozen identity.
        binding.enabled = False
        connection.enabled = False
        await session.commit()
        enqueued = []

        async def enqueue(self, node_run_id):
            enqueued.append(node_run_id)
            return "isolated-enqueue"

        monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", enqueue)
        await jobs.recover_interrupted_provider_jobs({})
        assert run.id in enqueued
        # Cancellation on a recovery-queued row must not erase its remote task.
        await session.refresh(run)
        assert run.status == "queued" and run.cancellation_requested_at is not None
        await GenerationService(session, SimpleNamespace()).cancel_generation(
            project=project,
            operation_id=run.id,
        )
        assert run.status == "cancel_requested"
        await session.commit()
        if outcome == "cancel_ack_lost":
            with pytest.raises(asyncio.CancelledError):
                await jobs.execute_node_run({}, str(run.id))
            await jobs.recover_interrupted_provider_jobs({})
        result = await jobs.execute_node_run({}, str(run.id))
        await session.rollback()
        await set_rls_context(
            session, user_id=user.id, workspace_id=workspace_id, project_id=project_id
        )
        await session.refresh(run)
        await session.refresh(op)
        await session.refresh(shot)
        assert op.selection_plan["execution_identity"] == frozen
        assert calls["create"] == 1 and calls["cancel"] == 1
        assert set(polled_ids) == {remote_id}
        assert shot.formal_keyframe_artifact_id is None
        node = await session.get(GraphNode, run.graph_node_id)
        assert node.latest_successful_run_id != run.id
        artifacts = list(
            (
                await session.execute(select(Artifact).where(Artifact.produced_by_run_id == run.id))
            ).scalars()
        )
        if outcome == "cancelled":
            assert run.status == op.status == result["status"] == "cancelled"
            assert artifacts == []
        else:
            assert run.status == result["status"] == "completed_after_cancel"
            assert op.status == "succeeded"
            assert len(artifacts) == 1 and artifacts[0].id == run.result_artifact_id
            assert len(artifacts[0].content_hash) == 64 and artifacts[0].byte_size > 0
    finally:
        # Emit bounded structured evidence into the JUnit report, not raw wire data.
        async with factory() as observer:
            observed = await observer.get(NodeRun, run_ids[1]) if "run_ids" in locals() else None
            if observed is not None:
                observed_ops = list(
                    (
                        await observer.execute(
                            select(ProviderOperation).where(
                                ProviderOperation.node_run_id == observed.id
                            )
                        )
                    ).scalars()
                )
                observed_artifacts = list(
                    (
                        await observer.execute(
                            select(Artifact).where(Artifact.produced_by_run_id == observed.id)
                        )
                    ).scalars()
                )
                evidence = {
                    "case": outcome,
                    "node_run_status": observed.status,
                    "error_code": observed.error_code,
                    "calls": calls,
                    "polled_remote_ids": sorted(set(polled_ids)),
                    "operation_statuses": [item.status for item in observed_ops],
                    "frozen_binding_ids": [str(item.model_binding_id) for item in observed_ops],
                    "request_fingerprints": [item.request_fingerprint for item in observed_ops],
                    "frozen_identity_verified": all(
                        isinstance((item.selection_plan or {}).get("execution_identity"), dict)
                        for item in observed_ops
                    ),
                    "artifacts": [
                        {
                            "sha256": item.content_hash,
                            "bytes": item.byte_size,
                            "produced_by_run_id": str(item.produced_by_run_id),
                        }
                        for item in observed_artifacts
                    ],
                }
                record_property("matrix_evidence", json.dumps(evidence, sort_keys=True))
        registry_module._registry.pop((FAKE_PROVIDER, FAKE_PROFILE), None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_state",
    ["queued", "missing", "failed", "unavailable", "late_unadopted", "newer_success"],
)
async def test_dependency_matrix_stops_before_provider(
    pg_session, monkeypatch, source_state, record_property
):
    from app.execution.models import GraphEdge
    from app.execution.runtime_invariants import evaluate_required_dependencies
    from arq import Retry
    from test_phase5_restart_recovery_pg import _seed_graph_and_run

    session = pg_session
    user, project_id, workspace_id = await _project(session)
    run = await _seed_graph_and_run(
        session, project_id=project_id, user_id=user.id, node_key="keyframe", node_type="keyframe"
    )
    upstream = GraphNode(
        graph_version_id=run.graph_version_id,
        node_key="prompt",
        node_type="prompt_compose",
        display_name="Prompt",
        cacheable=True,
    )
    session.add(upstream)
    await session.flush()
    session.add(
        GraphEdge(
            graph_version_id=run.graph_version_id,
            upstream_node_id=upstream.id,
            downstream_node_id=run.graph_node_id,
            input_port="prompt",
            output_port="prompt",
            required=True,
        )
    )
    artifact = Artifact(
        project_id=project_id,
        artifact_type="document",
        storage_state="available",
        object_key=f"r5/{uuid4().hex}",
        content_hash="d" * 64,
        mime_type="application/json",
        byte_size=2,
    )
    session.add(artifact)
    await session.flush()
    latest_id = None
    if source_state != "missing":
        status = "queued" if source_state == "queued" else "failed"
        if source_state in {"unavailable", "late_unadopted"}:
            status = "completed_after_cancel" if source_state == "late_unadopted" else "completed"
        source = NodeRun(
            project_id=project_id,
            graph_version_id=run.graph_version_id,
            graph_node_id=upstream.id,
            attempt_no=1,
            idempotency_key=f"r5-source:{uuid4().hex}",
            input_hash="c" * 64,
            status=status,
            created_by=user.id,
            result_artifact_id=artifact.id if status.startswith("completed") else None,
        )
        session.add(source)
        await session.flush()
        if source_state == "unavailable":
            artifact.storage_state = "quarantined"
        if source_state == "newer_success":
            latest = NodeRun(
                project_id=project_id,
                graph_version_id=run.graph_version_id,
                graph_node_id=upstream.id,
                attempt_no=2,
                parent_run_id=source.id,
                idempotency_key=f"r5-source:{uuid4().hex}",
                input_hash="d" * 64,
                status="completed",
                created_by=user.id,
                result_artifact_id=artifact.id,
            )
            session.add(latest)
            await session.flush()
            latest_id = latest.id
    await session.commit()
    decision = await evaluate_required_dependencies(session, run=run)
    if source_state == "newer_success":
        assert decision.action == "ready" and decision.dependencies[0].run_id == latest_id
    else:
        factory = async_sessionmaker(session.bind, expire_on_commit=False)
        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)

        async def forbidden(*args, **kwargs):
            raise AssertionError("Dependency rejection must never enter Provider execution")

        monkeypatch.setattr("app.execution.product_path.execute_media_node_run", forbidden)
        if source_state == "queued":
            assert decision.action == "defer"
            with pytest.raises(Retry):
                await jobs.execute_node_run({}, str(run.id))
        else:
            expected = {
                "missing": "UPSTREAM_RUN_MISSING",
                "failed": "UPSTREAM_TERMINAL_FAILURE",
                "late_unadopted": "UPSTREAM_TERMINAL_FAILURE",
                "unavailable": "UPSTREAM_ARTIFACT_MISSING",
            }[source_state]
            result = await jobs.execute_node_run({}, str(run.id))
            assert result["status"] == "failed" and result["error_code"] == expected
            await session.refresh(run)
            assert run.error_code == expected
    assert (
        list(
            (
                await session.execute(
                    select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
                )
            ).scalars()
        )
        == []
    )
    record_property(
        "matrix_evidence",
        json.dumps(
            {
                "case": source_state,
                "decision": decision.action,
                "error_code": decision.error_code,
                "provider_operations": 0,
                "newest_attempt_id": str(latest_id),
                "node_run_status": run.status,
            },
            sort_keys=True,
        ),
    )


@pytest.mark.asyncio
async def test_queue_failure_is_durable_on_postgres(pg_session, monkeypatch, record_property):
    from app.shared.errors import ValidationAppError
    from test_phase5_restart_recovery_pg import _seed_graph_and_run

    session = pg_session
    user, project_id, workspace_id = await _project(session)
    run = await _seed_graph_and_run(
        session, project_id=project_id, user_id=user.id, node_key="keyframe", node_type="keyframe"
    )
    await session.commit()

    async def unavailable(*args, **kwargs):
        raise ConnectionError("isolated Redis outage")

    monkeypatch.setattr("arq.create_pool", unavailable)
    with pytest.raises(ValidationAppError, match="QUEUE_UNAVAILABLE"):
        await NodeRunScheduler(session).enqueue_node_run_only(run.id)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as observer:
        persisted = await observer.get(NodeRun, run.id)
        assert persisted.status == "failed" and persisted.error_code == "QUEUE_UNAVAILABLE"
        assert (
            list(
                (
                    await observer.execute(
                        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
                    )
                ).scalars()
            )
            == []
        )
        record_property(
            "matrix_evidence",
            json.dumps(
                {
                    "case": "queue_unavailable",
                    "node_run_status": persisted.status,
                    "error_code": persisted.error_code,
                    "provider_operations": 0,
                },
                sort_keys=True,
            ),
        )


@pytest.mark.asyncio
async def test_concurrent_cancel_consumers_send_at_most_one_remote_request(
    pg_session, record_property
):
    from datetime import UTC, datetime

    from app.execution.product_path import _request_remote_cancellation_once
    from test_phase5_restart_recovery_pg import _seed_graph_and_run

    session = pg_session
    user, project_id, workspace_id = await _project(session)
    run = await _seed_graph_and_run(
        session,
        project_id=project_id,
        user_id=user.id,
        node_key="video",
        node_type="video",
        status="cancel_requested",
    )
    run.cancellation_requested_at = datetime.now(UTC)
    remote_id = f"concurrent-{uuid4().hex}"
    resume = ProviderResumeToken(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        remote_task_id=remote_id,
        query_kind="task_id",
    )
    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider=FAKE_PROVIDER,
        actual_model="controlled",
        protocol_profile=FAKE_PROFILE,
        request_fingerprint="d" * 64,
        status="submitted",
        provider_operation_id=remote_id,
        resume_token=resume.model_dump(mode="json"),
        execution_path_version="unified-v1",
    )
    session.add(op)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    ready = asyncio.Event()
    arrivals = 0
    calls = []

    class CancelOnly:
        async def cancel_video(self, token):
            calls.append(token.remote_task_id)
            return CancelResult(status="unsupported")

    async def consumer():
        nonlocal arrivals
        async with factory() as db:
            local_run = await db.get(NodeRun, run.id)
            local_op = await db.get(ProviderOperation, op.id)
            arrivals += 1
            if arrivals == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 10)
            result = await _request_remote_cancellation_once(
                db, run=local_run, operation=local_op, runtime=CancelOnly(), resume=resume
            )
            await db.commit()
            return result

    assert await asyncio.gather(consumer(), consumer()) == [(True, False), (True, False)]
    await session.refresh(op)
    assert calls == [remote_id]
    assert op.cancel_requested_at is not None
    assert op.response_summary["cancel_result_status"] == "unsupported"
    record_property(
        "matrix_evidence",
        json.dumps(
            {
                "case": "concurrent_cancel",
                "remote_cancel_calls": len(calls),
                "operation_status": op.status,
                "node_run_status": run.status,
                "remote_id": remote_id,
            },
            sort_keys=True,
        ),
    )
