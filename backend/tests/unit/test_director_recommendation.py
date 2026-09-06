"""V1 G4A Proactive Director Recommendation tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.recommendation import (
    DirectorRecommendationRequest,
    DirectorRecommendationService,
)
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
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


async def _seed(session: AsyncSession) -> tuple[User, Scene, Shot]:
    user = User(
        email=f"rec-{uuid4().hex}@example.com",
        display_name="Rec Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    from app.access.models import Project

    project = Project(
        workspace_id=workspace.id,
        name="Recommendation Project",
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="intro",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        shot_type="medium",
        camera_move="static",
        visual_description="A turns toward the window",
        dialogue="You knew?",
        status="draft",
        sort_order=1,
        director_state={"action": {"description": "turns"}},
        image_prompt="keyframe",
        video_prompt="video",
        version=3,
    )
    session.add(shot)
    await session.flush()
    return user, scene, shot


def _request(scene: Scene, shot: Shot, *, version: int | None = None):
    return DirectorRecommendationRequest(
        scene_id=scene.id,
        shot_id=shot.id,
        expected_shot_version=shot.version if version is None else version,
    )


@pytest.mark.asyncio
async def test_recommendation_without_instruction_reads_server_facts(
    session: AsyncSession,
) -> None:
    user, scene, shot = await _seed(session)
    result = await DirectorRecommendationService(session).recommend(
        project_id=shot.project_id,
        actor=user,
        request=_request(scene, shot),
    )
    assert result.category == "PERFORMANCE"
    assert result.base_shot_version == 3
    assert "medium static" in result.current_state
    assert result.suggested_change
    assert result.reason
    assert result.expected_effect
    assert result.risk
    assert "shot.director_state.performance" in result.affected_facts
    assert shot.version == 3


@pytest.mark.asyncio
async def test_stale_recommendation_fails_closed(session: AsyncSession) -> None:
    user, scene, shot = await _seed(session)
    with pytest.raises(ConflictError) as raised:
        await DirectorRecommendationService(session).recommend(
            project_id=shot.project_id,
            actor=user,
            request=_request(scene, shot, version=2),
        )
    assert raised.value.details["code"] == "SHOT_RECOMMENDATION_STALE"


@pytest.mark.asyncio
async def test_invalid_forbidden_fields_fail_closed(session: AsyncSession) -> None:
    user, scene, shot = await _seed(session)

    class BadTransport:
        async def generate(self, _context) -> object:
            return {
                "base_shot_version": shot.version,
                "scope": "shot",
                "category": "PERFORMANCE",
                "current_state": "x",
                "suggested_change": "x",
                "reason": "x",
                "expected_effect": "x",
                "risk": "x",
                "affected_facts": [],
                "typed_operations": [
                    {"op": "update_director_state", "design": {"node_run_id": "bad"}}
                ],
            }

    with pytest.raises(ValidationAppError) as raised:
        await DirectorRecommendationService(session, transport=BadTransport()).recommend(
            project_id=shot.project_id,
            actor=user,
            request=_request(scene, shot),
        )
    assert raised.value.details["code"] == "INVALID_DIRECTOR_RECOMMENDATION"


@pytest.mark.asyncio
async def test_foreign_shot_is_invisible(session: AsyncSession) -> None:
    user, scene, shot = await _seed(session)
    _other_user, other_scene, other_shot = await _seed(session)
    with pytest.raises(NotFoundError):
        await DirectorRecommendationService(session).recommend(
            project_id=shot.project_id,
            actor=user,
            request=_request(other_scene, other_shot),
        )


def test_request_does_not_accept_user_instruction() -> None:
    with pytest.raises(ValueError):
        DirectorRecommendationRequest.model_validate(
            {
                "scene_id": str(uuid4()),
                "shot_id": str(uuid4()),
                "expected_shot_version": 1,
                "user_instruction": "客户端不能上传指令",
            }
        )
