"""Final Film Timeline scoping and fail-closed unit tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.editing.models import EditSession
from app.production.final_film import _load_timeline_refs, render_final_film
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import select
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


async def _seed_project(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"final-{uuid4().hex}@example.com",
        display_name="Final Owner",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Final Film Project",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="9:16",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    return project, user


@pytest.mark.asyncio
async def test_load_timeline_refs_requires_persisted_version(session: AsyncSession) -> None:
    project, _user = await _seed_project(session)
    session.add(
        EditSession(
            project_id=project.id,
            name="Timeline v2",
            status="draft",
            version=2,
            timeline={"clips": [], "metadata": {}},
            production_lineage={"lineage_readonly": True},
            created_by=_user.id,
        )
    )
    await session.commit()
    edit_id = (
        await session.execute(
            select(EditSession.id).where(EditSession.project_id == project.id)
        )
    ).scalar_one()
    with pytest.raises(ValidationAppError) as exc:
        await _load_timeline_refs(
            session,
            project_id=project.id,
            edit_session_id=edit_id,
            expected_timeline_version=3,
        )
    assert exc.value.details.get("code") == "TIMELINE_VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_render_empty_timeline_fails_closed(session: AsyncSession) -> None:
    project, user = await _seed_project(session)
    edit = EditSession(
        project_id=project.id,
        name="Empty timeline",
        status="draft",
        version=1,
        timeline={"clips": [], "metadata": {}},
        production_lineage={"lineage_readonly": True},
        created_by=user.id,
    )
    session.add(edit)
    await session.commit()
    with pytest.raises(ValidationAppError) as exc:
        await render_final_film(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=1,
            actor_id=user.id,
        )
    assert exc.value.details.get("code") == "EMPTY_TIMELINE"


@pytest.mark.asyncio
async def test_missing_edit_session_is_not_found(session: AsyncSession) -> None:
    project, user = await _seed_project(session)
    with pytest.raises(NotFoundError):
        await render_final_film(
            session,
            project_id=project.id,
            edit_session_id=uuid4(),
            expected_timeline_version=None,
            actor_id=user.id,
        )
