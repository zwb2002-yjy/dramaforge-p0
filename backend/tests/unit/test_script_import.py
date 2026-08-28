"""Golden script import → Episode/Scene/Shot + canonical character."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.api.v1.scripts import (
    ShotCanvasUpdateBody,
    ShotChangeProposalCreate,
    create_shot_change_proposal,
    get_project_script,
    update_shot_canvas,
)
from app.assets import models as _am  # noqa: F401
from app.assets.characters import register_lead_character, require_canonical_for_shot
from app.assets.models import (
    CanvasRevision,
    Episode,
    Scene,
    ScriptDocument,
    Shot,
    ShotChangeProposal,
)
from app.assets.script_import import import_script, parse_script_markdown
from app.creation import models as _cm  # noqa: F401
from app.creation.service import CreationService
from app.delivery import models as _dm  # noqa: F401
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.production import models as _pm  # noqa: F401
from app.providers.fake import FakeFluxAdapter
from app.shared.base import Base
from app.shared.errors import ConflictError, ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fixtures" / "scripts" / "p0_10_shots.md"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
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
async def test_get_script_workspace_reads_text_and_episodes(session: AsyncSession) -> None:
    user, project = await _project(session)
    text = GOLDEN.read_text(encoding="utf-8")
    await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=text,
        actor=user,
    )
    await session.commit()

    ws = await get_project_script(project.id, user, session)
    assert ws.document is not None
    assert ws.document.raw_text == text
    assert ws.document.filename == "p0_10_shots.md"
    assert len(ws.document.content_hash) == 64
    assert len(ws.episodes) == 1
    episode = ws.episodes[0]
    assert episode.episode_number == 1
    assert episode.title == "Neon Rain Lead"
    assert len(episode.scenes) == 3
    assert [scene.shot_count for scene in episode.scenes] == [3, 4, 3]


@pytest.mark.asyncio
async def test_get_script_workspace_empty_when_no_import(session: AsyncSession) -> None:
    user, project = await _project(session)
    ws = await get_project_script(project.id, user, session)
    assert ws.document is None
    assert ws.episodes == []


@pytest.mark.asyncio
async def test_get_script_workspace_deterministic_latest_document(session: AsyncSession) -> None:
    user, project = await _project(session)
    first_text = GOLDEN.read_text(encoding="utf-8")
    # A second, different script that parses to a valid scene/shot structure.
    second_text = first_text.replace("Lin Xia", "Han Yu").replace("Neon Rain Lead", "Old Town")
    await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=first_text,
        actor=user,
    )
    await session.commit()
    # Force the first document's created_at clearly earlier so the ordering rule
    # (created_at DESC, id DESC) is deterministic regardless of the clock-tick
    # tie and the random uuid4 id (which would otherwise make the "latest"
    # ambiguous when both docs share the same created_at).
    first_doc = (
        await session.execute(
            select(ScriptDocument).where(
                ScriptDocument.project_id == project.id, ScriptDocument.filename == "p0_10_shots.md"
            )
        )
    ).scalar_one()
    old = datetime(2020, 1, 1, tzinfo=UTC)
    first_doc.created_at = old
    await session.commit()
    await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots_2.md",
        text=second_text,
        actor=user,
    )
    await session.commit()

    ws = await get_project_script(project.id, user, session)
    assert ws.document is not None
    # The latest import (newer created_at) wins via created_at DESC, id DESC.
    assert ws.document.content_hash == hash_of(second_text)
    assert ws.document.filename == "p0_10_shots_2.md"
    docs = (
        await session.execute(
            select(ScriptDocument).where(ScriptDocument.project_id == project.id)
        )
    ).scalars().all()
    assert len(docs) == 2


def hash_of(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    assert "tracking Lin Xia as she walks toward camera" in next(
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
    assert ref.artifact_id == char.canonical_artifact_id
@pytest.mark.asyncio
async def test_canvas_revision_persists_with_optimistic_lock(session: AsyncSession) -> None:
    user, project = await _project(session)
    result = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=GOLDEN.read_text(encoding="utf-8"),
        actor=user,
    )
    await session.commit()
    shot = (await session.execute(select(Shot).where(Shot.id == result.shot_ids[0]))).scalar_one()
    original_version = shot.version
    response = await update_shot_canvas(
        project.id,
        shot.id,
        ShotCanvasUpdateBody(
            expected_version=original_version,
            visual_description="用户确认后的正式镜头语义",
            shot_type=shot.shot_type,
            camera_move="slow_push_in",
            dialogue=shot.dialogue,
        ),
        user,
        session,
        None,
    )
    await session.commit()
    assert response.revision_number == 1
    assert response.shot.version == original_version + 1
    revision = (
        await session.execute(
            select(CanvasRevision).where(CanvasRevision.id == response.revision_id)
        )
    ).scalar_one()
    assert revision.visual_description == "用户确认后的正式镜头语义"
    with pytest.raises(ConflictError):
        await update_shot_canvas(
            project.id,
            shot.id,
            ShotCanvasUpdateBody(
                expected_version=original_version,
                visual_description="过期编辑器覆盖",
                shot_type=shot.shot_type,
                camera_move="static",
                dialogue=shot.dialogue,
            ),
            user,
            session,
            None,
        )
@pytest.mark.asyncio
async def test_shot_change_proposal_is_idempotent_and_confirms_on_canvas_revision(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    result = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename="p0_10_shots.md",
        text=GOLDEN.read_text(encoding="utf-8"),
        actor=user,
    )
    await session.commit()
    shot = (await session.execute(select(Shot).where(Shot.id == result.shot_ids[0]))).scalar_one()
    body = ShotChangeProposalCreate(
        idempotency_key="proposal-1",
        summary="补齐动作因果",
        expected_version=shot.version,
        replacement_payload={"visual_description": "新的导演语义"},
        affected_node_keys=["video"],
        reusable_artifact_ids=["keyframe-1"],
    )
    first = await create_shot_change_proposal(project.id, shot.id, body, user, session, None)
    second = await create_shot_change_proposal(project.id, shot.id, body, user, session, None)
    assert first.proposal.id == second.proposal.id
    assert first.proposal.status == "awaiting_confirmation"
    stored = (
        await session.execute(
            select(ShotChangeProposal).where(ShotChangeProposal.id == first.proposal.id)
        )
    ).scalar_one()
    assert stored.base_shot_version == shot.version