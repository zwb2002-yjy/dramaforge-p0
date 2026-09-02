"""P7-02 DirectorThread / DirectorMessage ORM tests (03 §62)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.director.assistant_models import DirectorMessage, DirectorThread
from app.shared.base import Base
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


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"thread-{uuid4().hex}@example.com",
        display_name="Thread",
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
    return project, user


@pytest.mark.asyncio
async def test_thread_and_messages_round_trip(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot_id = uuid4()
    thread = DirectorThread(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_id,
        title="Shot assistant",
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    session.add_all([
        DirectorMessage(
            thread_id=thread.id, project_id=project.id, role="user",
            content="建议改低机位", created_by=user.id,
        ),
        DirectorMessage(
            thread_id=thread.id, project_id=project.id, role="assistant",
            content="已生成 proposal", created_by=None,
        ),
    ])
    await session.flush()
    messages = (
        await session.execute(
            select(DirectorMessage).where(DirectorMessage.thread_id == thread.id)
        )
    ).scalars().all()
    assert len(messages) == 2
    assert [m.role for m in messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_thread_unique_per_scope(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot_id = uuid4()
    session.add(DirectorThread(
        project_id=project.id, scope_type="shot", scope_entity_id=shot_id, created_by=user.id
    ))
    await session.flush()
    session.add(DirectorThread(
        project_id=project.id, scope_type="shot", scope_entity_id=shot_id, created_by=user.id
    ))
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await session.flush()
