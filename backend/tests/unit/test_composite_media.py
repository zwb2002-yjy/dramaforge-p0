"""Contract tests for local composite media execution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Organization, OrganizationMember, User
from app.access.projects import ProjectService
from app.config import clear_settings_cache
from app.creation import models as _cm  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.composite_media import (
    CompositeInputs,
    CompositeRenderError,
    deterministic_composite_test_bytes,
)
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.product_path import execute_media_node_run
from app.production import models as _pm  # noqa: F401
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore, reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_SOURCE_BYTES = {
    "video": b"\x00\x00\x00\x18ftypmp42source-video",
    "voice": b"RIFF\x24\x00\x00\x00WAVEfmt source-voice",
    "subtitle": b"1\n00:00:00,000 --> 00:00:02,000\nComposite subtitle\n",
}
_SOURCE_META = {
    "video": ("video", "video/mp4"),
    "voice": ("audio", "audio/wav"),
    "subtitle": ("subtitle", "application/x-subrip"),
}


@dataclass(frozen=True)
class SourceMedia:
    run: NodeRun
    artifact: Artifact
    data: bytes


@dataclass(frozen=True)
class CompositeFixture:
    composite_run: NodeRun
    store: InMemoryObjectStore
    sources: dict[str, SourceMedia]


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


class ExplodingAdapter:
    provider = "kling"

    def __init__(self) -> None:
        self.called = False

    async def create(self, request: dict[str, object]) -> dict[str, object]:
        self.called = True
        raise AssertionError(f"composite must not call Provider: {request}")

    async def poll(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"composite must not poll Provider: {remote_task_id}")

    async def fetch_cost(self, remote_task_id: str) -> dict[str, object]:
        raise AssertionError(f"composite must not fetch Provider cost: {remote_task_id}")


async def _make_composite_fixture(
    session: AsyncSession,
    *,
    source_keys: set[str] | None = None,
    unavailable_key: str | None = None,
    unreadable_key: str | None = None,
    invalid_hash_key: str | None = None,
    add_older_video: bool = False,
) -> CompositeFixture:
    source_keys = set(_SOURCE_BYTES) if source_keys is None else source_keys
    user = User(
        email=f"composite-{uuid4().hex[:8]}@example.com",
        display_name="Composite",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"Composite-{uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=MemberRole.OWNER.value,
        )
    )
    await session.flush()
    project = await ProjectService(session).create_project(
        organization_id=org.id,
        name="Composite media",
        aspect_ratio="9:16",
        actor=user,
    )
    shot_id = uuid4()
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key="composite-test",
        created_by=user.id,
        definition={},
    )
    assert graph.current_version_id is not None
    nodes: dict[str, GraphNode] = {}
    for key in (*_SOURCE_BYTES, "composite"):
        node = GraphNode(
            graph_version_id=graph.current_version_id,
            node_key=key,
            node_type=key,
            display_name=key.title(),
            cacheable=True,
        )
        session.add(node)
        nodes[key] = node
    await session.flush()

    store = reset_object_store_for_tests()
    sources: dict[str, SourceMedia] = {}
    if add_older_video and "video" in source_keys:
        await _add_source_media(
            session,
            store=store,
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            node=nodes["video"],
            user_id=user.id,
            shot_id=shot_id,
            key="video",
            data=b"\x00\x00\x00\x18ftypmp42older-video",
            attempt_no=1,
        )

    for key in source_keys:
        sources[key] = await _add_source_media(
            session,
            store=store,
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            node=nodes[key],
            user_id=user.id,
            shot_id=shot_id,
            key=key,
            data=_SOURCE_BYTES[key],
            attempt_no=2 if key == "video" and add_older_video else 1,
            storage_state="quarantined" if key == unavailable_key else "available",
            store_bytes=key != unreadable_key,
            invalid_hash=key == invalid_hash_key,
        )

    composite_run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=nodes["composite"].id,
        attempt_no=1,
        idempotency_key=f"composite:{uuid4()}",
        input_hash="c" * 64,
        status="queued",
        input_snapshot={"shot_id": str(shot_id), "node_key": "composite"},
        created_by=user.id,
    )
    session.add(composite_run)
    await session.flush()
    return CompositeFixture(composite_run=composite_run, store=store, sources=sources)


async def _add_source_media(
    session: AsyncSession,
    *,
    store: InMemoryObjectStore,
    project_id: UUID,
    graph_version_id: UUID,
    node: GraphNode,
    user_id: UUID,
    shot_id: UUID,
    key: str,
    data: bytes,
    attempt_no: int,
    storage_state: str = "available",
    store_bytes: bool = True,
    invalid_hash: bool = False,
) -> SourceMedia:
    source_run = NodeRun(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node_id=node.id,
        attempt_no=attempt_no,
        idempotency_key=f"{key}:{attempt_no}:{uuid4()}",
        input_hash=key * 16,
        status="completed",
        input_snapshot={"shot_id": str(shot_id), "node_key": key},
        created_by=user_id,
    )
    session.add(source_run)
    await session.flush()
    artifact_type, mime_type = _SOURCE_META[key]
    object_key = f"projects/{project_id}/source/{key}/{source_run.id}"
    if store_bytes:
        stored = await store.put_bytes(object_key=object_key, data=data, mime_type=mime_type)
        content_hash = "0" * 64 if invalid_hash else stored.content_hash
        byte_size = stored.byte_size
    else:
        content_hash = hashlib.sha256(data).hexdigest()
        byte_size = len(data)
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        storage_state=storage_state,
        object_key=object_key,
        content_hash=content_hash,
        mime_type=mime_type,
        byte_size=byte_size,
        produced_by_run_id=source_run.id,
    )
    session.add(artifact)
    await session.flush()
    source_run.result_artifact_id = artifact.id
    await session.flush()
    return SourceMedia(run=source_run, artifact=artifact, data=data)


def _media_lineage(sources: dict[str, SourceMedia]) -> dict[str, dict[str, str]]:
    return {
        key: {
            "artifact_id": str(source.artifact.id),
            "object_key": source.artifact.object_key,
            "content_hash": source.artifact.content_hash,
            "mime_type": source.artifact.mime_type,
            "source_node_run_id": str(source.run.id),
        }
        for key, source in sources.items()
    }


@pytest.mark.asyncio
async def test_composite_runs_locally_with_complete_media_lineage(
    session: AsyncSession,
) -> None:
    fixture = await _make_composite_fixture(session, add_older_video=True)
    adapter = ExplodingAdapter()

    result = await execute_media_node_run(
        session,
        node_run_id=fixture.composite_run.id,
        store=fixture.store,
        flux=adapter,  # type: ignore[arg-type]
    )

    expected_inputs = _media_lineage(fixture.sources)
    expected_bytes = deterministic_composite_test_bytes(
        CompositeInputs(
            media_inputs=expected_inputs,
            video=fixture.sources["video"].data,
            voice=fixture.sources["voice"].data,
            subtitle=fixture.sources["subtitle"].data,
        )
    )
    run = await session.get(NodeRun, fixture.composite_run.id)
    artifact = await session.get(Artifact, result.artifact_id)
    operations = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id == fixture.composite_run.id
            )
        )
    ).scalars().all()

    assert adapter.called is False
    assert operations == []
    assert run is not None
    assert run.status == "completed"
    assert run.provider_cost == Decimal("0")
    assert run.platform_cost == Decimal("0")
    assert run.input_snapshot["media_inputs"] == expected_inputs
    assert run.output_summary["media_inputs"] == expected_inputs
    assert artifact is not None
    assert artifact.artifact_type == "video"
    assert artifact.mime_type == "video/mp4"
    assert await fixture.store.get_bytes(object_key=artifact.object_key) == expected_bytes
    assert result.provider_operation_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_key", ("video", "voice", "subtitle"))
async def test_composite_missing_required_input_fails_without_provider_operation(
    session: AsyncSession,
    missing_key: str,
) -> None:
    fixture = await _make_composite_fixture(
        session,
        source_keys=set(_SOURCE_BYTES) - {missing_key},
    )
    adapter = ExplodingAdapter()

    with pytest.raises(ValidationAppError, match="COMPOSITE_INPUT_MISSING"):
        await execute_media_node_run(
            session,
            node_run_id=fixture.composite_run.id,
            store=fixture.store,
            flux=adapter,  # type: ignore[arg-type]
        )

    run = await session.get(NodeRun, fixture.composite_run.id)
    operations = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id == fixture.composite_run.id
            )
        )
    ).scalars().all()
    assert adapter.called is False
    assert operations == []
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "COMPOSITE_INPUT_MISSING"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unavailable_key", "unreadable_key", "invalid_hash_key"),
    (("voice", None, None), (None, "subtitle", None), (None, None, "video")),
)
async def test_composite_unavailable_or_unreadable_input_fails_closed(
    session: AsyncSession,
    unavailable_key: str | None,
    unreadable_key: str | None,
    invalid_hash_key: str | None,
) -> None:
    fixture = await _make_composite_fixture(
        session,
        unavailable_key=unavailable_key,
        unreadable_key=unreadable_key,
        invalid_hash_key=invalid_hash_key,
    )
    adapter = ExplodingAdapter()

    with pytest.raises(ValidationAppError, match="COMPOSITE_INPUT_MISSING"):
        await execute_media_node_run(
            session,
            node_run_id=fixture.composite_run.id,
            store=fixture.store,
            flux=adapter,  # type: ignore[arg-type]
        )

    run = await session.get(NodeRun, fixture.composite_run.id)
    operations = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id == fixture.composite_run.id
            )
        )
    ).scalars().all()
    assert adapter.called is False
    assert operations == []
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "COMPOSITE_INPUT_MISSING"


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ("development", "production"))
async def test_composite_non_test_render_uses_ffmpeg_and_fails_closed(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    fixture = await _make_composite_fixture(session)
    adapter = ExplodingAdapter()
    called = False

    async def failing_ffmpeg(_: CompositeInputs) -> bytes:
        nonlocal called
        called = True
        raise CompositeRenderError("ffmpeg test failure")

    monkeypatch.setenv("APP_ENV", app_env)
    clear_settings_cache()
    monkeypatch.setattr("app.execution.composite_media._render_with_ffmpeg", failing_ffmpeg)
    try:
        with pytest.raises(ValidationAppError, match="COMPOSITE_RENDER_FAILED"):
            await execute_media_node_run(
                session,
                node_run_id=fixture.composite_run.id,
                store=fixture.store,
                flux=adapter,  # type: ignore[arg-type]
            )
    finally:
        clear_settings_cache()

    run = await session.get(NodeRun, fixture.composite_run.id)
    operations = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id == fixture.composite_run.id
            )
        )
    ).scalars().all()
    assert called is True
    assert adapter.called is False
    assert operations == []
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "COMPOSITE_RENDER_FAILED"
    assert run.input_snapshot["media_inputs"] == _media_lineage(fixture.sources)
