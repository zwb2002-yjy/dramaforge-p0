"""P4-10 Execution trace tests (03 §40)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.trace import build_execution_trace
from app.shared.base import Base
from app.shared.errors import NotFoundError
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_run_with_trace(
    session: AsyncSession,
) -> tuple[Project, NodeRun, User]:
    user = User(
        email=f"trace-{uuid4().hex}@example.com",
        display_name="Trace",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    from app.production.service import GraphService

    graphs = GraphService(session)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="trace-graph",
        created_by=user.id,
        definition={"nodes": [{"key": "video", "type": "video"}], "edges": []},
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = await graphs.publish(version_id=materialized.version.id, published_by=user.id)
    node = materialized.nodes["video"]
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        idempotency_key=f"trace:{uuid4().hex}",
        input_hash="a" * 64,
        status="completed",
        input_snapshot={
            "node_key": "video",
            "workbench_plan": {
                "semantic_intent": {"intent": "shot_video"},
                "prompt": "formal keyframe + prompt",
                "capability": "video.image_to_video",
                "resolved_model": {
                    "resolved_model_id": "agnes/agnes-video-v2.0",
                    "provider_model_binding_id": str(uuid4()),
                    "manifest_hash": "c" * 64,
                    "invoke_model_value": "agnes-video-v2.0",
                },
                "planned_references": [
                    {
                        "purpose": "first_frame",
                        "role": "first_frame",
                        "delivery": "exact",
                        "artifact_id": str(uuid4()),
                    }
                ],
                "accepted_approximations": ["camera_language"],
            },
        },
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider="agnes",
        actual_model="agnes-video-v2.0",
        request_fingerprint="d" * 64,
        request_summary={
            "effective_request_redacted": {"prompt": "..."},
            "translation_report": {"transformations": []},
        },
    )
    session.add(operation)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="stored",
        object_key=f"obj/{uuid4().hex}",
        content_hash="e" * 64,
        mime_type="video/mp4",
        byte_size=2,
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    return project, run, user


@pytest.mark.asyncio
async def test_trace_returns_full_secret_free_trace(session: AsyncSession) -> None:
    project, run, _user = await _seed_run_with_trace(session)
    trace = await build_execution_trace(
        session,
        project_id=project.id,
        run_id=run.id,
    )
    assert trace.status == "completed"
    assert trace.node_key == "video"
    assert trace.director_intent == {"intent": "shot_video"}
    assert trace.prompt == "formal keyframe + prompt"
    assert trace.capability == "video.image_to_video"
    assert trace.actual_provider == "agnes"
    assert trace.actual_model == "agnes-video-v2.0"
    assert trace.effective_request_redacted["effective_request_redacted"] == {"prompt": "..."}
    assert trace.approximations == ["camera_language"]
    assert len(trace.resolved_asset_versions) == 1
    assert trace.artifact is not None
    assert trace.artifact["artifact_type"] == "video"
    payload = trace.model_dump(mode="json")
    forbidden = ("api_key", "authorization", "ciphertext", "password", "bearer", "secret")

    def walk(value: object) -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(frag in normalized for frag in forbidden):
                    hits.append(key)
                hits.extend(walk(child))
        elif isinstance(value, list):
            for child in value:
                hits.extend(walk(child))
        return hits

    assert walk(payload) == []


@pytest.mark.asyncio
async def test_trace_raises_for_unknown_run(session: AsyncSession) -> None:
    project, _run, _user = await _seed_run_with_trace(session)
    with pytest.raises(NotFoundError):
        await build_execution_trace(
            session,
            project_id=project.id,
            run_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_trace_without_plan_snapshot_is_graceful(session: AsyncSession) -> None:
    project, run, _user = await _seed_run_with_trace(session)
    run.input_snapshot = {}
    await session.flush()
    trace = await build_execution_trace(
        session,
        project_id=project.id,
        run_id=run.id,
    )
    assert trace.director_intent == {}
    assert trace.prompt is None
    assert trace.resolved_asset_versions == []
    assert trace.actual_provider == "agnes"  # still from ProviderOperation
