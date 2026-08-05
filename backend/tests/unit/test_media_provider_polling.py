"""Regression coverage for long-running paid media Provider tasks."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.config import Settings
from app.creation import models as _cm  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.execution.product_path import execute_media_node_run
from app.production import models as _pm  # noqa: F401
from app.production.service import GraphService
from app.providers.agnes import AgnesHubClient
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()
    reset_object_store_for_tests()


class DelayedVideoAdapter:
    provider = "kling"

    def __init__(self, statuses: list[str]) -> None:
        self._statuses = iter(statuses)
        self.poll_count = 0
        self.blobs = {"provider-video-1": b"\x00\x00\x00\x18ftypmp42test-video"}

    async def create(self, request: dict[str, object]) -> dict[str, object]:
        assert request["kind"] == "video"
        return {"remote_task_id": "provider-video-1", "status": "queued"}

    async def poll(self, remote_task_id: str) -> dict[str, object]:
        assert remote_task_id == "provider-video-1"
        self.poll_count += 1
        return {"status": next(self._statuses)}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
        assert remote_task_id == "provider-video-1"
        return {"amount": 1.25, "currency": "USD"}


class ResumeOnlyAgnesVideoAdapter:
    provider = "agnes"
    protocol_profile = "agnes_cn_v1"

    def __init__(self) -> None:
        self.poll_count = 0
        self.blobs = {"provider-video-resume": b"\x00\x00\x00\x18ftypmp42resumed-video"}

    async def create(self, request: dict[str, object]) -> dict[str, object]:
        raise AssertionError(f"persisted remote task must not be created again: {request}")

    async def poll(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"Agnes resume must use the persisted query kind: {remote_task_id}")

    async def poll_persisted(
        self,
        remote_task_id: str,
        *,
        query_kind: str | None,
    ) -> dict[str, object]:
        assert remote_task_id == "provider-video-resume"
        assert query_kind == "video_id"
        self.poll_count += 1
        return {"status": "succeeded"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
        assert remote_task_id == "provider-video-resume"
        return {"amount": 0.75, "currency": "USD"}


class CreateFailureAdapter:
    provider = "kling"

    def __init__(self) -> None:
        self.poll_called = False

    async def create(self, request: dict[str, object]) -> dict[str, object]:
        assert request["kind"] == "video"
        return {
            "remote_task_id": "generated-local-id",
            "status": "failed",
            "error": "agnes video http 400: {'error': 'unsupported input'}",
        }

    async def poll(self, remote_task_id: str) -> dict[str, object]:
        self.poll_called = True
        raise AssertionError(f"poll must not run after create failure: {remote_task_id}")

    async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"cost lookup must not run after create failure: {remote_task_id}")


class CreateExceptionAdapter:
    provider = "kling"

    async def create(self, request: dict[str, object]) -> dict[str, object]:
        assert request["kind"] == "video"
        raise TimeoutError()

    async def poll(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"poll must not run after create exception: {remote_task_id}")

    async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"cost lookup must not run after create exception: {remote_task_id}")


def _agnes_settings() -> Settings:
    return Settings(
        app_env="development",
        agnes_enabled=True,
        agnes_api_key="test-provider-key",
        agnes_base_url="https://agnes.example/v1",
    )


@pytest.mark.asyncio
async def test_agnes_image_create_is_single_attempt_on_503() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url.path == "/v1/images/generations"
        return httpx.Response(503, json={"error": "hub overloaded"})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(prompt="cinematic archive room")

    assert attempts == 1
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_agnes_image_policy_refusal_is_not_hidden_rewritten_post() -> None:
    prompts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(str(json.loads(request.content)["prompt"]))
        return httpx.Response(
            400,
            json={"error": {"message": "Unable to generate this content."}},
        )

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(prompt="a rejected creative prompt")

    assert prompts == ["a rejected creative prompt"]
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_BAD_REQUEST"


@pytest.mark.asyncio
async def test_agnes_image_i2i_uses_generation_json_and_redacted_summary() -> None:
    canonical = b"canonical-image-bytes"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        assert set(body) == {"model", "prompt", "size", "extra_body"}
        assert body["model"] == "agnes-image-2.1-flash"
        assert body["size"] == "1024x768"
        assert "image" not in {key for key in body if key != "extra_body"}
        assert body["extra_body"]["response_format"] == "url"
        assert len(body["extra_body"]["image"]) == 1
        assert body["extra_body"]["image"][0].startswith("data:image/png;base64,")
        return httpx.Response(200, json={"data": [{"url": "https://media.example/edit.png"}]})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(
        prompt="single adult portrait in a cafe",
        canonical_image_bytes=canonical,
        reference_artifact_id="artifact-1",
    )

    assert result["status"] == "succeeded"
    summary = result["request_summary"]
    assert summary["protocol_profile"] == "agnes_cn_v1"
    assert summary["operation"] == "image.i2i"
    assert summary["reference_artifact_ids"] == ["artifact-1"]
    assert summary["reference_fingerprints"] == [
        __import__("hashlib").sha256(canonical).hexdigest()
    ]
    serialized = json.dumps(summary)
    assert "base64" not in serialized
    assert "canonical-image-bytes" not in serialized


@pytest.mark.asyncio
async def test_agnes_image_bad_request_has_stable_code_and_no_repost() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": {"message": "invalid image size"}})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(prompt="cinematic archive room")

    assert attempts == 1
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_BAD_REQUEST"


@pytest.mark.asyncio
async def test_agnes_video_i2v_top_level_image_and_dual_remote_ids() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/videos"
        body = json.loads(request.content)
        assert body == {
            "model": "agnes-video-v2.0",
            "prompt": "cinematic rain-soaked harbor",
            "image": "https://references.example/opaque-token",
            "num_frames": 121,
            "frame_rate": 24,
            "height": 1280,
            "width": 720,
        }
        return httpx.Response(
            200,
            json={"video_id": "video-123", "task_id": "task-456", "status": "queued"},
        )

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_video(
        prompt="cinematic rain-soaked harbor",
        image_url="https://references.example/opaque-token",
        reference_artifact_ids=["artifact-1"],
        reference_fingerprints=["a" * 64],
    )

    assert result["remote_task_id"] == "video-123"
    assert result["remote_secondary_id"] == "task-456"
    assert result["query_kind"] == "video_id"
    serialized = json.dumps(result["request_summary"])
    assert "opaque-token" not in serialized


@pytest.mark.asyncio
async def test_agnes_video_i2v_bare_base64_first_frame_without_data_url_prefix() -> None:
    """Official Video V2.0: image accepts public URL or raw Base64 body, NOT a
    data:...;base64, prefix (verified against Agnes wiki + vendor support)."""
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/videos"
        body = json.loads(request.content)
        assert "data:" not in body["image"]  # bare Base64 body, no Data URL prefix
        import base64 as _b64

        assert _b64.b64decode(body["image"]).startswith(b"\x89PNG")
        assert body["num_frames"] == 121
        assert body["frame_rate"] == 24
        assert body["height"] == 1280
        assert body["width"] == 720
        assert "image_url" not in body
        return httpx.Response(
            200,
            json={"video_id": "video-duri", "task_id": "task-duri", "status": "queued"},
        )

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_video(
        prompt="controlled camera motion",
        image_bytes=b"\x89PNG\r\n\x1a\nfake-png-bytes",
        image_mime="image/png",
        reference_artifact_ids=["artifact-1"],
        reference_fingerprints=["a" * 64],
    )

    assert result["remote_task_id"] == "video-duri"
    assert result["remote_secondary_id"] == "task-duri"
    assert result["request_summary"]["reference_transport"] == "base64_raw"
    serialized = json.dumps(result["request_summary"])
    assert "data:image" not in serialized  # request summary never stores a Data URL


@pytest.mark.asyncio
async def test_agnes_video_i2v_rejects_combined_image_sources() -> None:
    async def _never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be reached for invalid source combination")

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(_never))
    with pytest.raises(ValueError, match="cannot be combined"):
        await client.create_video(
            prompt="motion",
            image_url="https://references.example/token",
            image_bytes=b"\x89PNG fake",
        )


@pytest.mark.asyncio
async def test_agnes_video_rate_limit_is_not_reposted_and_keeps_retry_after() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "17"},
            json={"error": "rate limited"},
        )

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_video(
        prompt="cinematic rain-soaked harbor",
        image_url="https://references.example/opaque-token",
    )

    assert attempts == 1
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_RATE_LIMITED"
    assert result["retry_after_seconds"] == 17.0


@pytest.mark.asyncio
async def test_agnes_video_poll_rate_limit_keeps_polling_same_task() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/videos/video-123"
        return httpx.Response(
            429,
            headers={"Retry-After": "17"},
            json={"error": "rate limited"},
        )

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.poll_video("video-123", query_kind="task_id")

    assert result["status"] == "running"
    assert result["poll_error"] == "http_429"
    assert result["error_code"] == "PROVIDER_RATE_LIMITED"
    assert result["retry_after_seconds"] == 17.0


@pytest.mark.asyncio
async def test_agnes_video_poll_server_error_is_transient_not_terminal() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "overloaded"})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.poll_video("video-123", query_kind="task_id")

    assert result["status"] == "running"
    assert result["error_code"] == "PROVIDER_POLL_TRANSIENT"
    assert result["poll_error"] == "http_503"


@pytest.mark.asyncio
async def test_agnes_video_poll_not_found_remains_terminal() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    result = await client.poll_video("video-123", query_kind="task_id")

    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_REQUEST_FAILED"
    assert "error" in result


@pytest.mark.asyncio
async def test_agnes_video_invalid_shape_fails_before_network() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = AgnesHubClient(_agnes_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match=r"8n \+ 1"):
        await client.create_video(
            prompt="motion",
            image_url="https://references.example/token",
            num_frames=120,
        )
    with pytest.raises(ValueError, match="first-frame reference"):
        await client.create_video(prompt="motion")
    assert calls == 0


async def _video_run(session: AsyncSession) -> NodeRun:
    user = User(
        email=f"poll-{uuid4().hex[:8]}@example.com",
        display_name="P",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Poll-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id, name="Provider polling", aspect_ratio="9:16", actor=user
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="poll-test",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"video:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={"plan": {"prompt": "a real delayed video"}},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    return run


@pytest.mark.asyncio
async def test_video_waits_for_late_provider_completion(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _video_run(session)
    adapter = DelayedVideoAdapter(["running", "running", "succeeded"])

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.execution.product_path.asyncio.sleep", no_sleep)
    result = await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    assert result.node_type == "video"
    assert adapter.poll_count == 3
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.provider_operation_id == "provider-video-1"
    assert op.status == "succeeded"
    assert op.response_summary["poll_count"] == 3


@pytest.mark.asyncio
async def test_video_poll_transport_error_keeps_remote_task_and_retries(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _video_run(session)

    class PollTimeoutThenSuccessAdapter(DelayedVideoAdapter):
        async def poll(self, remote_task_id: str) -> dict[str, Any]:
            self.poll_count += 1
            if self.poll_count == 1:
                return {"status": "running", "poll_error": "ReadTimeout"}
            return {"status": "succeeded", "artifact_uri": "fake://provider-video-1"}

    adapter = PollTimeoutThenSuccessAdapter([])

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.execution.product_path.asyncio.sleep", no_sleep)
    result = await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    assert result.node_type == "video"
    assert adapter.poll_count == 2
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.provider_operation_id == "provider-video-1"
    assert op.status == "succeeded"
    assert op.response_summary["poll_count"] == 2


@pytest.mark.asyncio
async def test_video_poll_throttle_is_not_terminal_and_honors_retry_after(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _video_run(session)

    class PollThrottleThenSuccessAdapter(DelayedVideoAdapter):
        async def poll(self, remote_task_id: str) -> dict[str, Any]:
            self.poll_count += 1
            if self.poll_count == 1:
                return {
                    "status": "running",
                    "poll_error": "http_429",
                    "error_code": "PROVIDER_RATE_LIMITED",
                    "retry_after_seconds": 12.0,
                }
            return {"status": "succeeded", "artifact_uri": "fake://provider-video-1"}

    adapter = PollThrottleThenSuccessAdapter([])
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.execution.product_path.asyncio.sleep", record_sleep)
    result = await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    assert result.node_type == "video"
    assert adapter.poll_count == 2
    assert slept == [12.0]  # max(5s interval, Retry-After 12s), not the raw interval
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.status == "succeeded"
    assert op.response_summary["last_poll_error"] == "http_429"
    assert op.response_summary["poll_error_count"] == 1


@pytest.mark.asyncio
async def test_video_poll_error_evidence_survives_crash_before_terminal(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _video_run(session)

    class PollThenCrashAdapter(DelayedVideoAdapter):
        async def poll(self, remote_task_id: str) -> dict[str, Any]:
            self.poll_count += 1
            if self.poll_count == 1:
                return {"status": "running", "poll_error": "http_503", "http_status": 503}
            raise RuntimeError("worker killed mid-poll")

    adapter = PollThenCrashAdapter([])

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.execution.product_path.asyncio.sleep", no_sleep)
    with pytest.raises(RuntimeError, match="worker killed mid-poll"):
        await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    # The transient poll-error bookkeeping was committed inside the loop, so it
    # survives the crash even though no terminal/timeout path ever ran.
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.response_summary["poll_error_count"] == 1
    assert op.response_summary["last_poll_error"] == "http_503"
    assert op.response_summary["last_poll_http_status"] == 503


@pytest.mark.asyncio
async def test_agnes_video_worker_restart_resumes_persisted_operation_without_create(
    session: AsyncSession,
) -> None:
    run = await _video_run(session)
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=run.attempt_no,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider="agnes",
        actual_model="agnes-video-v2.0",
        provider_operation_id="provider-video-resume",
        remote_secondary_id="task-video-resume",
        protocol_profile="agnes_cn_v1",
        request_fingerprint="b" * 64,
        status="submitted",
        request_summary={"reference_transport": "short_lived_https"},
        response_summary={"create_status": "queued", "query_kind": "video_id"},
    )
    session.add(operation)
    await session.commit()
    run_id = run.id
    operation_id = operation.id
    session.expunge_all()

    adapter = ResumeOnlyAgnesVideoAdapter()
    result = await execute_media_node_run(
        session,
        node_run_id=run_id,
        flux=adapter,  # type: ignore[arg-type]
    )

    assert result.node_type == "video"
    assert adapter.poll_count == 1
    operations = list(
        (
            await session.execute(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(operations) == 1
    assert operations[0].id == operation_id
    assert operations[0].provider_operation_id == "provider-video-resume"
    assert operations[0].status == "succeeded"
    assert operations[0].response_summary["query_kind"] == "video_id"


@pytest.mark.asyncio
async def test_video_provider_failure_keeps_remote_operation_lineage(
    session: AsyncSession,
) -> None:
    run = await _video_run(session)
    adapter = DelayedVideoAdapter(["failed"])

    with pytest.raises(ValidationAppError, match="PROVIDER_FAILED"):
        await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.provider_operation_id == "provider-video-1"
    assert op.status == "failed"
    assert op.error_code == "PROVIDER_FAILED"
    failed_run = await session.get(NodeRun, run.id)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error_code == "PROVIDER_FAILED"
    assert failed_run.finished_at is not None
    assert failed_run.output_summary["status"] == "failed"


@pytest.mark.asyncio
async def test_video_create_failure_does_not_poll_and_preserves_create_error(
    session: AsyncSession,
) -> None:
    run = await _video_run(session)
    adapter = CreateFailureAdapter()

    with pytest.raises(ValidationAppError, match="PROVIDER_CREATE_FAILED: agnes video http 400"):
        await execute_media_node_run(session, node_run_id=run.id, flux=adapter)  # type: ignore[arg-type]

    assert adapter.poll_called is False
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.provider_operation_id is None
    assert op.status == "failed"
    assert op.error_code == "PROVIDER_CREATE_FAILED"
    assert op.error_summary == "agnes video http 400: {'error': 'unsupported input'}"
    assert op.response_summary["create_error"] == op.error_summary
    failed_run = await session.get(NodeRun, run.id)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error_code == "PROVIDER_CREATE_FAILED"
    assert failed_run.error_summary == op.error_summary


@pytest.mark.asyncio
async def test_video_create_exception_becomes_auditable_terminal_failure(
    session: AsyncSession,
) -> None:
    run = await _video_run(session)

    with pytest.raises(
        ValidationAppError,
        match="PROVIDER_CREATE_FAILED: provider create raised TimeoutError",
    ):
        await execute_media_node_run(
            session,
            node_run_id=run.id,
            flux=CreateExceptionAdapter(),  # type: ignore[arg-type]
        )

    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.provider_operation_id is None
    assert op.status == "failed"
    assert op.error_code == "PROVIDER_CREATE_FAILED"
    assert op.error_summary == "provider create raised TimeoutError"
    assert op.response_summary["create_error"] == op.error_summary
    failed_run = await session.get(NodeRun, run.id)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error_code == "PROVIDER_CREATE_FAILED"
    assert failed_run.error_summary == op.error_summary
