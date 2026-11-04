"""One submit and durable short observations across queue loss and redelivery."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.events.models import OutboxEvent
from app.events.outbox import StreamPublisher
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.runtime import (
    CompiledImageRequest,
    PollResult,
    ProviderResumeToken,
    ProviderRuntimeResolver,
    SubmissionDiagnostics,
    SubmissionResult,
)
from app.runtime.scheduler import NodeRunScheduler
from app.workers import jobs
from PIL import Image
from sqlalchemy import select
from tests.unit.test_provider_recovery import recovery, seed

__all__ = ["recovery"]


async def test_http_failure_evidence_survives_worker_commit(recovery, monkeypatch):
    import httpx
    import pytest
    from app.config import Settings
    from app.execution import provider_execution
    from app.providers.agnes import AgnesRuntime
    from app.providers.runtime import CompiledVideoRequest
    from app.shared.errors import ValidationAppError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            503,
            headers={"x-request-id": "req-persisted"},
            json={"detail": "No healthy video upstream"},
        )

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="synthetic-key"),
        transport=httpx.MockTransport(handler),
    )
    compiled = CompiledVideoRequest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-2.5-flash",
        operation="video.generate",
        request_schema_version="2026-11-03",
        wire_request={"model": "agnes-video-2.5-flash", "prompt": "test", "mode": "text"},
    )

    async def prepare(session, *, run, **kwargs):
        op = ProviderOperation(
            node_run_id=run.id,
            operation_kind="video.generate",
            actual_provider="agnes",
            actual_model="agnes-video-2.5-flash",
            status="submission_started",
            request_fingerprint="a" * 64,
            execution_path_version="unified-v1",
        )
        session.add(op)
        await session.commit()
        return SimpleNamespace(operation=op, compiled=compiled, runtime=runtime, identity_json={})

    monkeypatch.setattr(provider_execution, "prepare_media_submission", prepare)
    async with recovery.factory() as session:
        node = await session.get(GraphNode, recovery.node.id)
        run = NodeRun(
            project_id=recovery.project.id,
            graph_version_id=node.graph_version_id,
            graph_node_id=node.id,
            idempotency_key=uuid4().hex,
            input_hash="a" * 64,
            status="running",
            created_by=recovery.user.id,
            input_snapshot={},
        )
        session.add(run)
        await session.commit()
        with pytest.raises(ValidationAppError, match="PROVIDER_CREATE_FAILED"):
            await provider_execution._execute_unified_media_node_run(
                session,
                run=run,
                node=node,
                node_type="video",
                snap={},
                obj_store=SimpleNamespace(),
                prompt="test",
                canonical_image_bytes=None,
                lead_identity_required=False,
                has_canonical_binding=False,
            )
        run_id = run.id
    async with recovery.factory() as session:
        op = (
            await session.scalars(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run_id)
            )
        ).one()
        assert (
            op.response_summary["submission_diagnostics"]["response_request_id"] == "req-persisted"
        )
        assert (
            op.response_summary["submission_diagnostics"]["response_error"]
            == "No healthy video upstream"
        )
        assert op.response_summary["create_http_status"] == 503
        assert (await session.get(NodeRun, run_id)).status == "failed"
    assert len(calls) == 1


async def test_lost_submission_persistence_without_remote_id_never_resubmits(recovery, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    (run_id,) = await seed(recovery, remote=False)
    async with recovery.factory() as session:
        (await session.get(NodeRun, run_id)).status = "queued"
        await session.commit()
    submission = AsyncMock(
        side_effect=DBAPIError(
            "synthetic lost submission commit",
            {},
            OSError("connection lost"),
            True,
        )
    )
    monkeypatch.setattr("app.execution.product_path.execute_media_node_run", submission)
    result = await jobs.execute_node_run({}, str(run_id))
    assert result == {"status": "failed", "error_code": "PROVIDER_SUBMISSION_UNKNOWN"}
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        operation = (await session.scalars(select(ProviderOperation))).one()
        assert run.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
        assert operation.status == "unknown_submission"
        assert operation.provider_operation_id is None
    await jobs.execute_node_run({}, str(run_id))
    submission.assert_awaited_once()


async def make_due(env, run_id):
    async with env.factory() as session:
        run = await session.get(NodeRun, run_id)
        run.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        for event in (await session.scalars(select(OutboxEvent))).all():
            event.next_attempt_at = run.next_attempt_at
        await session.commit()


async def test_submit_exits_then_one_poll_per_due_job_without_extra_create(recovery, monkeypatch):
    from app.execution import provider_execution

    identity = ExecutionIdentitySnapshot(
        resolved_model="test/image",
        resolution_source="project_snapshot",
        provider_model_binding_id=uuid4(),
        catalog_entry_id=uuid4(),
        model_revision="r1",
        manifest_hash="c" * 64,
        invoke_model_value="image",
        connection_id=uuid4(),
        connection_revision_id=uuid4(),
        credential_revision_id=uuid4(),
        capability="image.generate",
        mode_id="text-to-image",
        request_fingerprint="b" * 64,
    )
    resume = ProviderResumeToken(
        provider_type="test", protocol_profile="test-v1", remote_task_id="remote-1"
    )
    compiled = CompiledImageRequest(
        provider_type="test",
        protocol_profile="test-v1",
        model_id="image",
        operation="image.generate",
        wire_request={"model": "image", "prompt": "synthetic"},
        request_schema_version="1",
    )
    image = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, format="PNG")
    data = image.getvalue()
    polls = 0

    async def poll(token):
        nonlocal polls
        assert token == resume
        polls += 1
        if polls == 1:
            return PollResult(status="running", retry_after_seconds=60)
        if polls == 2:
            await asyncio.sleep(1)  # genuine observation deadline, no whole-job sleep
        return PollResult(status="succeeded", artifact_uri="https://unit.invalid/result")

    runtime = SimpleNamespace(
        submit_image=AsyncMock(
            return_value=SubmissionResult(
                status="queued",
                remote_task_id="remote-1",
                resume_token=resume,
                submission_diagnostics=SubmissionDiagnostics(
                    phase="accepted",
                    endpoint="https://unit.invalid/v1/videos",
                    duration_ms=12,
                    http_status=200,
                    response_request_id="req-retained",
                ),
            )
        ),
        submit_video=AsyncMock(side_effect=AssertionError("no video create")),
        poll_video=AsyncMock(side_effect=poll),
        fetch_cost=AsyncMock(return_value=SimpleNamespace(amount=None, cost_status="not_reported")),
    )
    resolver = AsyncMock(return_value=runtime)
    monkeypatch.setattr(ProviderRuntimeResolver, "resume_runtime_for_identity", resolver)
    monkeypatch.setattr(provider_execution, "POLL_OBSERVATION_TIMEOUT_SECONDS", 0.01)

    async def prepare(session, *, run, **kwargs):
        run.input_snapshot = {
            **run.input_snapshot,
            "execution_identity": identity.model_dump(mode="json"),
        }
        operation = ProviderOperation(
            node_run_id=run.id,
            operation_kind="image.generate",
            actual_provider="test",
            actual_model="image",
            protocol_profile="test-v1",
            execution_path_version="unified-v1",
            status="submission_started",
            request_fingerprint=identity.request_fingerprint,
            selection_plan={"execution_identity": identity.model_dump(mode="json")},
            request_summary={"execution_identity": identity.model_dump(mode="json")},
        )
        session.add(operation)
        await session.commit()
        return SimpleNamespace(
            operation=operation,
            compiled=compiled,
            runtime=runtime,
            identity_json=identity.model_dump(mode="json"),
        )

    prepare_mock = AsyncMock(side_effect=prepare)
    monkeypatch.setattr(provider_execution, "prepare_media_submission", prepare_mock)

    async def resolve_media(**kwargs):
        from app.execution.media_io import _resolve_media_file

        return await _resolve_media_file(**{**kwargs, "artifact_uri": data})

    monkeypatch.setattr(provider_execution, "_resolve_media_file", resolve_media)

    async def store(**kwargs):
        return SimpleNamespace(
            object_key=kwargs["object_key"],
            content_hash=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            mime_type="image/png",
        )

    monkeypatch.setattr(
        "app.execution.product_path.get_object_store", lambda: SimpleNamespace(put_file=store)
    )
    async with recovery.factory() as session:
        node = await session.get(GraphNode, recovery.node.id)
        node.node_type = node.node_key = "keyframe"
        run = NodeRun(
            project_id=recovery.project.id,
            graph_version_id=node.graph_version_id,
            graph_node_id=node.id,
            idempotency_key=uuid4().hex,
            input_hash="a" * 64,
            status="queued",
            created_by=recovery.user.id,
            input_snapshot={"prompt": "synthetic", "dispatch_generation": "original"},
        )
        session.add(run)
        await session.commit()
        run_id = run.id
    first = await asyncio.wait_for(jobs.execute_node_run({}, str(run_id)), timeout=2)
    assert first["status"] == "provider_pending"
    runtime.submit_image.assert_awaited_once_with(compiled)
    runtime.poll_video.assert_not_awaited()
    async with recovery.factory() as session:
        frozen = dict((await session.get(NodeRun, run_id)).input_snapshot)
        assert await NodeRunScheduler(session, publisher=StreamPublisher()).dispatch_pending() == 0
    assert (await jobs.execute_node_run({}, str(run_id)))["status"] == "not_due"

    # A failed Redis enqueue keeps the due remote task. It neither fails the
    # NodeRun nor erases the Outbox and cannot reach another submission.
    await make_due(recovery, run_id)
    enqueue = NodeRunScheduler._enqueue_node_run
    monkeypatch.setattr(
        NodeRunScheduler, "_enqueue_node_run", AsyncMock(side_effect=OSError("queue unavailable"))
    )
    async with recovery.factory() as session:
        await NodeRunScheduler(session, publisher=StreamPublisher()).dispatch_pending()
        assert (await session.get(NodeRun, run_id)).status == "queued"
    monkeypatch.setattr(NodeRunScheduler, "_enqueue_node_run", enqueue)
    for index in range(3):
        await make_due(recovery, run_id)
        async with recovery.factory() as session:
            await NodeRunScheduler(session, publisher=StreamPublisher()).dispatch_pending()
        result = await asyncio.wait_for(jobs.execute_node_run({}, str(run_id)), timeout=2)
        assert result["status"] in {"provider_pending", "completed"}, result
        async with recovery.factory() as session:
            run = await session.get(NodeRun, run_id)
            operation = (await session.scalars(select(ProviderOperation))).one()
            assert run.input_snapshot == frozen
            assert operation.provider_operation_id == "remote-1"
            assert (
                operation.response_summary["submission_diagnostics"]["response_request_id"]
                == "req-retained"
            )
            assert operation.resume_token == resume.model_dump(mode="json")
            assert operation.response_summary.get("poll_count") == index + 1, {
                "iteration": index,
                "result": result,
                "poll_calls": polls,
                "create_calls": runtime.submit_image.await_count,
                "summary": operation.response_summary,
            }
            if index < 2:
                assert result["status"] == "provider_pending"
                assert run.started_at is None
                remaining = (
                    run.next_attempt_at.replace(tzinfo=UTC) - datetime.now(UTC)
                ).total_seconds()
                assert remaining > (58 if index == 0 else 4)
                if index == 1:
                    assert (
                        operation.response_summary["last_poll_error"]
                        == "PROVIDER_POLL_OBSERVATION_TIMEOUT"
                    )
            else:
                assert result["status"] == "completed"
    assert polls == 3
    assert len(recovery.queue.admitted) == 3  # retained previous keys cannot suppress later polls
    runtime.submit_image.assert_awaited_once()
    prepare_mock.assert_awaited_once()
    runtime.submit_video.assert_not_awaited()
    assert all(call.kwargs["identity"] == identity for call in resolver.await_args_list)
