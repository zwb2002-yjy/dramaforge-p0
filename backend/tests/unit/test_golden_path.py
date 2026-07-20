"""Golden P0 path from fixtures/scripts/p0_10_shots.md."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.access.models import Organization, OrganizationMember, User
from app.access.projects import ProjectService
from app.assets import models as _am  # noqa: F401
from app.creation import models as _cm  # noqa: F401
from app.delivery import models as _dm  # noqa: F401
from app.events import models as _em  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.golden_path import run_golden_p0_path
from app.production import models as _pm  # noqa: F401
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests


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


@pytest.mark.asyncio
async def test_golden_path_10_shots_export(session: AsyncSession) -> None:
    user = User(
        email=f"g-{uuid4().hex[:8]}@example.com",
        display_name="G",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name="GoldOrg")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value
        )
    )
    project = await ProjectService(session).create_project(
        organization_id=org.id,
        name="Golden",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    result = await run_golden_p0_path(
        session, project_id=project.id, user_id=user.id, try_ffmpeg=False
    )
    assert result.shot_count == 10
    assert all(s.face_checked and s.continuity_checked for s in result.shots)
    assert result.export.timeline_hash
    assert result.export.srt_hash
    assert result.export.package_hash
    assert result.export.export_item_count >= 1
    # Shared store holds canonical + keyframe bytes
    store = get_object_store()
    assert await store.get_bytes(object_key=result.canonical_object_key)
