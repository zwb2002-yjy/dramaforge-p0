"""S4 multi-shot via Graph/NodeRun with partial subtitle rework."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.access import models as _a  # noqa: F401
from app.access.models import Workspace, User
from app.access.projects import ProjectService
from app.events import models as _e  # noqa: F401
from app.execution import models as _x  # noqa: F401
from app.execution.multi_shot import produce_shots, rework_subtitle_only
from app.production import models as _p  # noqa: F401
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[User, object]:
    user = User(
        email=f"ms{uuid4().hex[:8]}@ex.com",
        display_name="MS",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="MSO")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"MSP{uuid4().hex[:4]}",
        aspect_ratio="9:16",
        actor=user,
    )
    return user, project


@pytest.mark.asyncio
async def test_ten_shots_have_graphs_and_runs(session: AsyncSession) -> None:
    user, project = await _seed(session)
    shots = await produce_shots(
        session, project_id=project.id, user_id=user.id, n=10, budget=Decimal("500")
    )
    assert len(shots) == 10
    assert all(s.graph_id for s in shots)
    assert all(s.graph_version_id for s in shots)
    assert all("keyframe" in s.artifact_ids for s in shots)
    assert all(s.status == "review_passed" for s in shots)


@pytest.mark.asyncio
async def test_subtitle_rework_preserves_upstream_artifacts(session: AsyncSession) -> None:
    user, project = await _seed(session)
    shots = await produce_shots(
        session, project_id=project.id, user_id=user.id, n=2, budget=Decimal("100")
    )
    shot = shots[0]
    kf, vid, voice = (
        shot.artifact_ids["keyframe"],
        shot.artifact_ids["video"],
        shot.artifact_ids["voice"],
    )
    old_sub = shot.artifact_ids["subtitle"]
    await rework_subtitle_only(
        session,
        project_id=project.id,
        user_id=user.id,
        shot=shot,
        new_subtitle="Reworked",
        budget=Decimal("50"),
    )
    assert shot.artifact_ids["keyframe"] == kf
    assert shot.artifact_ids["video"] == vid
    assert shot.artifact_ids["voice"] == voice
    assert shot.artifact_ids["subtitle"] != old_sub
    assert shot.subtitle == "Reworked"
