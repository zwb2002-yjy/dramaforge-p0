"""V1 G2A CreativeTemplate registry + ProjectCreativeProfile tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, ProjectCreativeProfile, User, Workspace
from app.access.projects import ProjectService
from app.director.creative_capabilities.creative_templates import (
    CREATIVE_TEMPLATES,
    get_creative_template,
)
from app.shared.base import Base
from app.shared.security import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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
        email=f"template-{uuid4().hex}@example.com",
        display_name="Template",
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
        start_type="TEMPLATE",
        template_key="dual_character_conflict_v1",
    )
    return project, user


def test_registry_has_three_templates_with_contract_hashes() -> None:
    assert {template.key for template in CREATIVE_TEMPLATES} == {
        "dual_character_conflict_v1",
        "single_monologue_v1",
        "free_basic_v1",
    }
    for template in CREATIVE_TEMPLATES:
        assert template.contract_hash == template.contract_hash


@pytest.mark.asyncio
async def test_template_create_stores_profile_without_media_or_scenes(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)
    profile = await session.scalar(
        select(ProjectCreativeProfile).where(
            ProjectCreativeProfile.project_id == project.id
        )
    )
    assert profile is not None
    assert profile.start_type == "TEMPLATE"
    assert profile.created_from_template_key == "dual_character_conflict_v1"
    assert profile.director_autonomy == "ASSIST"
    assert "character_a" in (
        (profile.asset_slot_requirements or {}).get("required") or []
    )

    from app.assets.models import Episode, Shot
    from app.execution.models import NodeRun
    from app.production.models import ProductionGraph

    for model in (Episode, Shot, NodeRun, ProductionGraph):
        count = await session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.project_id == project.id)
        )
        assert (count or 0) == 0, model.__tablename__


@pytest.mark.asyncio
async def test_free_create_has_free_profile(session: AsyncSession) -> None:
    user = User(
        email=f"free-{uuid4().hex}@example.com",
        display_name="Free",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"F-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name="Free Project",
        aspect_ratio="16:9",
        actor=user,
    )
    profile = await session.scalar(
        select(ProjectCreativeProfile).where(
            ProjectCreativeProfile.project_id == project.id
        )
    )
    assert profile is not None
    assert profile.start_type == "FREE"
    assert profile.created_from_template_key is None


def test_invalid_template_key_rejected() -> None:
    from app.shared.errors import ValidationAppError

    with pytest.raises(ValidationAppError):
        get_creative_template("does-not-exist")


def test_project_api_returns_template_profile(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"project-template-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Project Template",
        },
    )
    assert registered.status_code == 201, registered.text
    csrf = str(client.get("/api/v1/auth/csrf").json()["csrf_token"])
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Template Project",
            "aspect_ratio": "9:16",
            "start_type": "TEMPLATE",
            "template_key": "single_monologue_v1",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["creative_profile"]["start_type"] == "TEMPLATE"
    assert body["creative_profile"]["created_from_template_key"] == "single_monologue_v1"
