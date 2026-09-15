"""Workbench plan: template recommendations must never look like applied controls."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.director.creative_capabilities.creative_templates import get_creative_template
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.base import Base
from app.shared.security import hash_password
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


async def _project(
    session: AsyncSession, *, start_type: str = "TEMPLATE", template_key: str | None = None
) -> tuple[User, Project]:
    user = User(
        email=f"plan-{uuid4().hex[:8]}@example.com",
        display_name="Plan",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:6]}",
        aspect_ratio="9:16",
        actor=user,
        start_type=start_type,
        template_key=template_key,
    )
    await session.commit()
    return user, project


async def _suggestions(
    session: AsyncSession, *, project: Project, semantic_intent: dict[str, object]
) -> list[object]:
    service = WorkbenchExecutionService(session, user_id=project.workspace_id)
    return await service._pending_creative_suggestions(
        project=project,
        semantic_intent=semantic_intent,
    )


TEMPLATE_KEY = "dual_character_conflict_v1"


def _template():
    template = get_creative_template(TEMPLATE_KEY)
    assert template is not None
    return template


@pytest.mark.asyncio
async def test_template_recommendations_that_are_not_consumed_are_reported(
    session: AsyncSession,
) -> None:
    """A template's style/skill/language picks are suggestions, not plan inputs."""
    template = _template()
    _user, project = await _project(session, template_key=template.key)

    suggestions = await _suggestions(session, project=project, semantic_intent={})
    keys = {item.key for item in suggestions}  # type: ignore[attr-defined]

    for style_id in template.recommended_style_ids:
        assert f"style:{style_id}" in keys
    for skill_id in template.recommended_skill_ids:
        assert f"skill:{skill_id}" in keys
    assert f"shot_language:{template.recommended_shot_language}" in keys
    assert f"genre:{template.recommended_genre}" in keys
    for item in suggestions:
        assert item.source == "template_recommendation"  # type: ignore[attr-defined]
        # Every entry explains why it is not part of the execution.
        reason = item.reason  # type: ignore[attr-defined]
        assert "不会" in reason or "不参与" in reason


@pytest.mark.asyncio
async def test_consumed_skill_guidance_is_not_reported_as_pending(
    session: AsyncSession,
) -> None:
    """Once a skill is compiled into the shot snapshot it stops being a suggestion."""
    template = _template()
    _user, project = await _project(session, template_key=template.key)
    consumed_skill = template.recommended_skill_ids[0]
    compiled_intent: dict[str, object] = {
        "skill_guidance": [{"skill_key": consumed_skill, "skill_version": 1}],
        "shot_language": {"coverage": "conversation"},
    }

    suggestions = await _suggestions(session, project=project, semantic_intent=compiled_intent)
    keys = {item.key for item in suggestions}  # type: ignore[attr-defined]

    assert f"skill:{consumed_skill}" not in keys
    # Still-pending skills keep their warning.
    for skill_id in template.recommended_skill_ids[1:]:
        assert f"skill:{skill_id}" in keys
    # A compiled shot language clears that suggestion.
    assert f"shot_language:{template.recommended_shot_language}" not in keys
    # The genre has no compiled consumer at all, so it stays a suggestion.
    assert f"genre:{template.recommended_genre}" in keys


@pytest.mark.asyncio
async def test_free_start_reports_no_template_suggestions(session: AsyncSession) -> None:
    _user, project = await _project(session, start_type="FREE", template_key=None)

    suggestions = await _suggestions(session, project=project, semantic_intent={})

    assert suggestions == []


def test_plan_exposes_the_suggestions_field() -> None:
    """The plan model carries the field the preview renders."""
    from app.production.execution_plan import WorkbenchExecutionPlan

    assert "pending_suggestions" in WorkbenchExecutionPlan.model_fields
    assert WorkbenchExecutionPlan.model_fields["pending_suggestions"].default_factory is list


def test_request_body_does_not_carry_the_suggestion_field() -> None:
    """Suggestions are plan output only; the caller's request body never sets them."""
    assert "pending_suggestions" not in WorkbenchExecutionInput.model_fields
