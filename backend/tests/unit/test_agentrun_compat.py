"""P7-01 AgentRun director_assist compatibility tests (03 §61)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.creation.models import AgentRun
from app.shared.base import Base
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


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"assist-{uuid4().hex}@example.com",
        display_name="Assist",
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
async def test_director_assist_run_without_planning_authorization(session: AsyncSession) -> None:
    project, user = await _seed(session)
    run = AgentRun(
        project_id=project.id,
        initiated_by=user.id,
        planning_authorization_id=None,
        operation="director_assist",
        status="queued",
        requested_capability="director.assist.v1",
        prompt_version="director-assist-v1",
        output_schema_version="proposal-v1",
        context_compiler_version="assistant-context-v1",
        input_hash="a" * 64,
        context_hash="b" * 64,
    )
    session.add(run)
    await session.flush()
    assert run.planning_authorization_id is None
    assert run.operation == "director_assist"


@pytest.mark.asyncio
async def test_director_assist_in_operation_enum(session: AsyncSession) -> None:
    from app.creation.models import _agent_operation

    assert "director_assist" in _agent_operation.enums
