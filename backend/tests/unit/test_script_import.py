"""Golden script import → Episode/Scene/Shot + canonical character."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.access.projects import ProjectService
from app.assets import models as _am  # noqa: F401
from app.assets.characters import register_lead_character, require_canonical_for_shot
from app.assets.models import Shot
from app.assets.script_import import import_script, parse_script_markdown
from app.creation import models as _cm  # noqa: F401
from app.delivery import models as _dm  # noqa: F401
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.production import models as _pm  # noqa: F401
from app.providers.fake import FakeFluxAdapter
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy import select

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
    org = Organization(name=f"SO-{uuid4().hex[:6]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    project = await ProjectService(session).create_project(
        organization_id=org.id,
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
