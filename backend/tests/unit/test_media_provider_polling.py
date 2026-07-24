"""Regression coverage for long-running paid media Provider tasks."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from app.access.models import Organization, OrganizationMember, User
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
from app.shared.enums import MemberRole
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
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


@pytest.mark.asyncio
async def test_agnes_image_retries_transient_503_before_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url.path == "/v1/images/generations"
        if attempts < 3:
            return httpx.Response(503, json={"error": "hub overloaded"})
        return httpx.Response(200, json={"data": [{"url": "https://media.example/image.png"}]})

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.providers.agnes.asyncio.sleep", no_sleep)
    client = AgnesHubClient(
        Settings(
            app_env="development",
            agnes_enabled=True,
            agnes_api_key="test-provider-key",
            agnes_base_url="https://agnes.example/v1",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.create_image(prompt="cinematic archive room")

    assert attempts == 3
    assert result["status"] == "succeeded"
    assert result["artifact_uri"] == "https://media.example/image.png"


async def _video_run(session: AsyncSession) -> NodeRun:
    user = User(
        email=f"poll-{uuid4().hex[:8]}@example.com",
        display_name="P",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"Poll-{uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    await session.flush()
    project = await ProjectService(session).create_project(
        organization_id=org.id, name="Provider polling", aspect_ratio="9:16", actor=user
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
