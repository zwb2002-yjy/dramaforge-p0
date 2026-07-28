"""Golden script import → Episode/Scene/Shot + canonical character."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Workspace, User
from app.access.projects import ProjectService
from app.assets import models as _am  # noqa: F401
from app.assets.characters import register_lead_character, require_canonical_for_shot
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.assets.script_import import import_script, parse_script_markdown
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery import models as _dm  # noqa: F401
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.production import models as _pm  # noqa: F401
from app.providers.fake import FakeFluxAdapter
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "scripts" / "p0_10_shots.md"


@pytest.fixture
async def session() -> AsyncSession:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()
    reset_object_store_for_tests()


async def _project(session: AsyncSession):
    user = User(
        email=f"s-{uuid4().hex[:8]}@example.com",
        display_name="S",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"SO-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"Script-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    return user, project


def test_parse_golden_fixture() -> None:
    text = GOLDEN.read_text(encoding="utf-8")
    parsed = parse_script_markdown(text)
    assert parsed.episode_number == 1
    assert parsed.lead_character == "Lin Xia"
    assert len(parsed.scenes) == 3
    assert sum(len(s.shots) for s in parsed.scenes) == 10
    assert parsed.scenes[0].shots[0].visual


@pytest.mark.asyncio
async def test_import_golden_creates_10_shots(session: AsyncSession) -> None:
    user, project = await _project(session)
    text = GOLDEN.read_text(encoding="utf-8")
    result = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text,
        actor=user,
    )
    assert result.shot_count == 10
    assert result.scene_count == 3
    assert result.lead_character == "Lin Xia"
    assert len(result.content_hash) == 64
    rows = list(
        (
            await session.execute(
                select(Shot).where(Shot.project_id == project.id).order_by(Shot.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 10
    assert rows[0].sort_order == 1
    assert rows[9].sort_order == 10
    assert "neon" in rows[0].visual_description.lower() or "Lin" in rows[0].visual_description


@pytest.mark.asyncio
async def test_import_same_script_twice_is_idempotent(session: AsyncSession) -> None:
    user, project = await _project(session)
    text = GOLDEN.read_text(encoding="utf-8")

    first = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text,
        actor=user,
    )
    await session.commit()
    second = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text,
        actor=user,
    )
    await session.commit()

    assert second.script_document_id == first.script_document_id
    assert second.episode_id == first.episode_id
    assert second.shot_ids == first.shot_ids
    documents = (
        await session.execute(
            select(ScriptDocument).where(ScriptDocument.project_id == project.id)
        )
    ).scalars().all()
    shots = (
        await session.execute(select(Shot).where(Shot.project_id == project.id))
    ).scalars().all()
    assert len(documents) == 1
    assert len(shots) == 10


@pytest.mark.asyncio
async def test_import_reconciles_materialized_agent_plan_shots(session: AsyncSession) -> None:
    user, base_project = await _project(session)
    service = CreationService(session)
    started = await service.start_project(
        workspace_id=base_project.workspace_id,
        name="Agent plan script reconciliation",
        aspect_ratio="9:16",
        actor=user,
        idea="A detective follows a neon-rain clue through one dangerous night.",
    )
    project_id = started.project_id
    brief = await service.generate_brief_agent(
        project_id=project_id,
        actor=user,
        idea="A detective follows a neon-rain clue through one dangerous night.",
        authorize=True,
    )
    confirmed = await service.confirm_brief(
        project_id=project_id,
        revision_id=brief.id,
        actor=user,
    )
    plan = await service.generate_plan_agent(
        project_id=project_id,
        actor=user,
        brief_revision_id=confirmed.id,
        authorize=True,
    )
    materialized = await service.confirm_plan_and_materialize(
        project_id=project_id,
        plan_id=plan.id,
        actor=user,
    )
    materialized_ids = set(materialized.shot_ids)

    result = await import_script(
        session,
        project_id=project_id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=GOLDEN.read_text(encoding="utf-8"),
        actor=user,
    )
    await session.commit()

    assert result.scene_count == 3
    assert result.shot_count == 10
    assert set(result.shot_ids) == materialized_ids

    scenes = {
        scene.id: scene.scene_number
        for scene in (
            await session.execute(
                select(Scene).join(Episode, Scene.episode_id == Episode.id).where(
                    Episode.project_id == project_id
                )
            )
        )
        .scalars()
        .all()
    }
    shots = (
        await session.execute(
            select(Shot)
            .where(Shot.project_id == project_id)
            .order_by(Shot.shot_number)
        )
    ).scalars().all()
    assert len(shots) == 10
    assert scenes[next(shot.scene_id for shot in shots if shot.shot_number == 4)] == 2
    assert "tracking Lin Xia through underpass" in next(
        shot.visual_description for shot in shots if shot.shot_number == 4
    )


@pytest.mark.asyncio
async def test_canonical_required_for_shot(session: AsyncSession) -> None:
    user, project = await _project(session)
    with pytest.raises(ValidationAppError, match="CANONICAL_REFERENCE_REQUIRED"):
        await require_canonical_for_shot(session, project_id=project.id)
    ad = FakeFluxAdapter()
    c = await ad.create({"prompt": "Lin Xia canonical", "kind": "keyframe"})
    char = await register_lead_character(
        session,
        project_id=project.id,
        name="Lin Xia",
        locked_prompt="Lin Xia consistent face",
        canonical_image_bytes=ad.blobs[c["remote_task_id"]],
        store=get_object_store(),
    )
    ref = await require_canonical_for_shot(session, project_id=project.id)
    assert ref.is_canonical
    assert ref.object_key == char.canonical_object_key
    assert len(ref.face_embedding) == 512
