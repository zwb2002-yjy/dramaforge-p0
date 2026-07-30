"""Regression for inspector blockers: approve gate, export gate, package meta, redis fail-closed."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access import models as _am  # noqa: F401
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets import models as _asm  # noqa: F401
from app.assets.models import Episode, Scene, Shot
from app.delivery import models as _dm  # noqa: F401
from app.delivery.export_service import build_project_export
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.shot_review import approve_shot, assert_shot_approvable, upload_manual_media
from app.production import models as _pm  # noqa: F401
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.shared.base import Base
from app.shared.enums import GraphStatus
from app.shared.errors import ForbiddenError, ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[User, Project, Shot]:
    user = User(
        email=f"ig-{uuid4().hex[:8]}@ex.com",
        display_name="IG",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"IG-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"IGP-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    session.add(project)
    await session.flush()
    ep = Episode(project_id=project.id, episode_number=1, title="E1")
    session.add(ep)
    await session.flush()
    scene = Scene(
        episode_id=ep.id,
        scene_number=1,
        location_name="street",
        time_of_day="night",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        sort_order=1,
        visual_description="neon",
        dialogue="hi",
        status="in_production",
    )
    session.add(shot)
    await session.flush()
    return user, project, shot


@pytest.mark.asyncio
async def test_approve_empty_shot_rejected(session: AsyncSession) -> None:
    user, project, shot = await _seed(session)
    with pytest.raises(ValidationAppError) as ei:
        await approve_shot(
            session,
            project_id=project.id,
            shot_id=shot.id,
            user_id=user.id,
            note="empty",
        )
    assert "APPROVE_GATE" in ei.value.message
    await session.refresh(shot)
    assert shot.status != "review_passed"


@pytest.mark.asyncio
async def test_export_without_approved_shots_rejected(session: AsyncSession) -> None:
    user, project, shot = await _seed(session)
    store = InMemoryObjectStore()
    art = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"projects/{project.id}/x.png",
        content_hash="a" * 64,
        mime_type="image/png",
        byte_size=10,
    )
    session.add(art)
    await session.flush()
    await store.put_bytes(
        object_key=art.object_key, data=b"\x89PNG" + b"0" * 8, mime_type="image/png"
    )

    with pytest.raises(ValidationAppError) as ei:
        await build_project_export(
            session,
            project_id=project.id,
            requested_by=user.id,
            shot_subtitles=[(str(shot.id), "hi")],
            store=store,
            try_ffmpeg=False,
            require_approved=True,
        )
    assert "EXPORT_GATE" in ei.value.message


@pytest.mark.asyncio
async def test_package_artifact_points_at_zip_not_json(session: AsyncSession) -> None:
    user, project, shot = await _seed(session)
    shot.status = "review_passed"
    await session.flush()
    store = InMemoryObjectStore()
    g = ProductionGraph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key="shot-p0-v1",
        created_by=user.id,
    )
    session.add(g)
    await session.flush()
    body: dict[str, object] = {"nodes": ["keyframe"]}
    gv = GraphVersion(
        graph_id=g.id,
        version_number=1,
        status=GraphStatus.PUBLISHED.value,
        definition_hash=definition_hash(body),
        definition=body,
    )
    session.add(gv)
    await session.flush()
    g.current_version_id = gv.id
    node = GraphNode(
        graph_version_id=gv.id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="keyframe",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=gv.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"t:{uuid4().hex}",
        input_hash="b" * 64,
        status="completed",
        input_snapshot={"shot_id": str(shot.id), "node_key": "keyframe"},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    art = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"projects/{project.id}/kf.png",
        content_hash="c" * 64,
        mime_type="image/png",
        byte_size=len(png),
        produced_by_run_id=run.id,
    )
    session.add(art)
    run.result_artifact_id = art.id
    await session.flush()
    await store.put_bytes(object_key=art.object_key, data=png, mime_type="image/png")

    exp = await build_project_export(
        session,
        project_id=project.id,
        requested_by=user.id,
        shot_subtitles=[(str(shot.id), "hi")],
        store=store,
        try_ffmpeg=False,
        require_approved=True,
        approved_shot_ids=[shot.id],
    )
    assert exp.package_hash
    pkg = (
        await session.execute(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.artifact_type == "export_package",
                Artifact.content_hash == exp.package_hash,
            )
        )
    ).scalar_one()
    assert pkg.object_key.endswith("package.zip")
    assert pkg.mime_type == "application/zip"
    assert pkg.byte_size > 0
    assert pkg.content_hash == exp.package_hash
    raw = await store.get_bytes(object_key=pkg.object_key)
    assert len(raw) == pkg.byte_size
    import hashlib

    assert hashlib.sha256(raw).hexdigest() == pkg.content_hash


@pytest.mark.asyncio
async def test_manual_media_retains_operator_and_note(session: AsyncSession) -> None:
    user, project, shot = await _seed(session)
    store = InMemoryObjectStore()
    art = await upload_manual_media(
        session,
        project_id=project.id,
        shot_id=shot.id,
        user_id=user.id,
        node_key="keyframe",
        data=b"\x89PNG" + b"x" * 20,
        mime_type="image/png",
        note="hand plate v1",
        store=store,
    )
    assert art.delete_reason is not None
    assert str(user.id) in art.delete_reason
    assert "hand plate v1" in art.delete_reason
    assert "audited_manual_upload" in art.delete_reason
    assert str(shot.id) in art.delete_reason


@pytest.mark.asyncio
async def test_manual_media_does_not_reassign_existing_artifact_lineage(
    session: AsyncSession,
) -> None:
    user, project, first_shot = await _seed(session)
    second_shot = Shot(
        project_id=project.id,
        scene_id=first_shot.scene_id,
        shot_number=first_shot.shot_number + 1,
        visual_description="second shot",
        dialogue="",
        status="draft",
    )
    session.add(second_shot)
    await session.flush()
    store = InMemoryObjectStore()
    data = b"\x89PNG" + b"same" * 8

    first = await upload_manual_media(
        session,
        project_id=project.id,
        shot_id=first_shot.id,
        user_id=user.id,
        node_key="keyframe",
        data=data,
        mime_type="image/png",
        store=store,
    )
    first_run_id = first.produced_by_run_id

    with pytest.raises(ValidationAppError, match="ARTIFACT_NOT_INDEPENDENT"):
        await upload_manual_media(
            session,
            project_id=project.id,
            shot_id=second_shot.id,
            user_id=user.id,
            node_key="keyframe",
            data=data,
            mime_type="image/png",
            store=store,
        )

    assert first.produced_by_run_id == first_run_id


@pytest.mark.asyncio
async def test_non_owner_cannot_resolve_project(session: AsyncSession) -> None:
    owner, project, _shot = await _seed(session)
    viewer = User(
        email=f"view-{uuid4().hex[:8]}@ex.com",
        display_name="V",
        password_hash=hash_password("password123"),
    )
    session.add(viewer)
    await session.flush()
    svc = ProjectService(session)

    with pytest.raises(ForbiddenError):
        await svc.get_project_for_owner(project_id=project.id, actor=viewer)
    assert await svc.get_project_for_owner(project_id=project.id, actor=owner) is project


@pytest.mark.asyncio
async def test_redis_stream_publisher_no_fallback_outside_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import clear_settings_cache
    from app.runtime.scheduler import RedisStreamPublisher

    monkeypatch.setenv("APP_ENV", "development")
    clear_settings_cache()
    pub = RedisStreamPublisher("redis://127.0.0.1:1/0")

    class BadClient:
        async def xadd(self, *_a, **_k):
            raise OSError("redis down")

    monkeypatch.setattr(pub, "_client", lambda: BadClient())
    with pytest.raises(ValidationAppError) as ei:
        await pub.publish("t", {"a": "1"})
    assert "OUTBOX_PUBLISH_FAILED" in ei.value.message
    monkeypatch.setenv("APP_ENV", "test")
    clear_settings_cache()


@pytest.mark.asyncio
async def test_enqueue_commits_before_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outbox/NodeRun must be committed before Redis enqueue is called."""
    from unittest.mock import AsyncMock, MagicMock

    from app.runtime.scheduler import AgentRunScheduler

    session = MagicMock()
    session.get = AsyncMock(
        return_value=MagicMock(
            id=uuid4(),
            project_id=uuid4(),
            status="queued",
        )
    )
    session.add = MagicMock()
    existing = MagicMock()
    existing.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=existing)
    session.flush = AsyncMock()

    order: list[str] = []

    async def track_commit():
        order.append("commit")

    async def track_enqueue(_nid):
        order.append("enqueue")
        return "job-1"

    session.commit = track_commit
    sched = AgentRunScheduler(session)
    monkeypatch.setattr(sched, "_enqueue_node_run", track_enqueue)

    jid = await sched.enqueue_node_run_only(uuid4())
    assert jid == "job-1"
    assert order == ["commit", "enqueue"]


@pytest.mark.asyncio
async def test_assert_approvable_requires_required_nodes(session: AsyncSession) -> None:
    _user, project, shot = await _seed(session)
    with pytest.raises(ValidationAppError):
        await assert_shot_approvable(session, project_id=project.id, shot_id=shot.id)
