"""P2-03 single-shot Director suggestion proposal-only contracts."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.suggestion import (
    ShotDirectorSuggestionContext,
    ShotDirectorSuggestionRequest,
    ShotDirectorSuggestionService,
)
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
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


async def _seed(session: AsyncSession) -> tuple[User, Project, Scene, Shot]:
    user = User(
        email=f"suggestion-{uuid4().hex}@example.com",
        display_name="Suggestion Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Suggestion Project",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
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
        dialogue="",
        status="draft",
        sort_order=1,
        director_state={
            "framing": {"shot_size": "medium", "angle": "eye_level"},
            "action": {"description": "turns"},
            "workflow_template_key": "single-pass-v1",
        },
        image_prompt="A cinematic keyframe",
        video_prompt="A slow turn toward the window",
        version=5,
    )
    session.add(shot)
    await session.flush()
    return user, project, scene, shot


def _request(
    scene: Scene, shot: Shot, *, version: int | None = None
) -> ShotDirectorSuggestionRequest:
    return ShotDirectorSuggestionRequest(
        scene_id=scene.id,
        shot_id=shot.id,
        expected_shot_version=shot.version if version is None else version,
        user_instruction="让情绪更克制，镜头缓慢推进",
    )


@pytest.mark.asyncio
async def test_suggestion_reads_server_truth_and_does_not_mutate(session: AsyncSession) -> None:
    user, project, scene, shot = await _seed(session)
    result = await ShotDirectorSuggestionService(session).suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, shot),
    )

    assert result.base_shot_version == 5
    assert "A cinematic keyframe" in result.suggested_image_prompt
    assert "缓慢推进" in result.suggested_video_prompt
    assert str(result.suggested_director_state.root["action"]["description"]).endswith(
        "让情绪更克制，镜头缓慢推进"
    )
    assert shot.version == 5
    assert shot.image_prompt == "A cinematic keyframe"
    assert shot.video_prompt == "A slow turn toward the window"
    stored = (await session.execute(select(Shot).where(Shot.id == shot.id))).scalar_one()
    assert stored.version == 5


@pytest.mark.asyncio
async def test_cross_project_or_scene_shot_is_not_visible(session: AsyncSession) -> None:
    user, project, scene, shot = await _seed(session)
    _other_user, other_project, other_scene, other_shot = await _seed(session)
    with pytest.raises(NotFoundError):
        await ShotDirectorSuggestionService(session).suggest(
            project_id=project.id,
            actor=user,
            request=_request(other_scene, other_shot),
        )
    with pytest.raises(NotFoundError):
        await ShotDirectorSuggestionService(session).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, other_shot),
        )
    assert other_project.id != project.id


@pytest.mark.asyncio
async def test_stale_expected_version_is_rejected_before_transport(session: AsyncSession) -> None:
    user, project, scene, shot = await _seed(session)

    class RecordingTransport:
        called = False

        async def generate(self, _context: ShotDirectorSuggestionContext) -> object:
            self.called = True
            return {}

    transport = RecordingTransport()
    with pytest.raises(ConflictError) as raised:
        await ShotDirectorSuggestionService(session, transport=transport).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot, version=4),
        )
    assert raised.value.details["code"] == "SHOT_SUGGESTION_STALE"
    assert transport.called is False


@pytest.mark.asyncio
async def test_invalid_structured_output_fails_closed_without_shot_mutation(
    session: AsyncSession,
) -> None:
    user, project, scene, shot = await _seed(session)

    class InvalidTransport:
        async def generate(self, _context: ShotDirectorSuggestionContext) -> object:
            return {
                "base_shot_version": 5,
                "suggested_image_prompt": "bad",
                "suggested_video_prompt": "bad",
                "suggested_director_state": {},
                "change_summary": "bad",
                "provider_request": {"url": "https://provider.invalid"},
            }

    with pytest.raises(ValidationAppError) as raised:
        await ShotDirectorSuggestionService(session, transport=InvalidTransport()).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot),
        )
    assert raised.value.details["code"] == "INVALID_DIRECTOR_SUGGESTION"
    assert shot.version == 5
    assert shot.image_prompt == "A cinematic keyframe"
    assert shot.video_prompt == "A slow turn toward the window"
    assert shot.director_state == {
        "framing": {"shot_size": "medium", "angle": "eye_level"},
        "action": {"description": "turns"},
        "workflow_template_key": "single-pass-v1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "container"),
    [
        ("provider_model_id", "expression"),
        ("providerModelId", "expression"),
        ("provider-model-id", "expression"),
        ("execution_plan", "continuity_constraints"),
        ("executionPlan", "continuity_constraints"),
        ("execution-plan", "continuity_constraints"),
        ("runtime_id", "video_reference_risk"),
        ("runtimeId", "video_reference_risk"),
        ("runtime-id", "video_reference_risk"),
        ("artifact_url", "expression"),
        ("artifactUrl", "expression"),
        ("artifact-url", "expression"),
        ("worker_queue", "continuity_constraints"),
        ("workerQueue", "continuity_constraints"),
        ("worker-queue", "continuity_constraints"),
        ("node_run_ids", "expression"),
        ("nodeRunIds", "expression"),
        ("node-run-ids", "expression"),
        ("nodeRunId", "continuity_constraints"),
        ("sql_query", "expression"),
        ("sqlQuery", "expression"),
        ("sql-query", "expression"),
        ("SQLQuery", "expression"),
        ("raw_sql_query", "expression"),
        ("raw-sql-query", "expression"),
        ("rawSqlQuery", "expression"),
    ],
)
async def test_nested_forbidden_field_families_fail_closed(
    session: AsyncSession,
    field_name: str,
    container: str,
) -> None:
    user, project, scene, shot = await _seed(session)

    class InvalidTransport:
        async def generate(self, _context: ShotDirectorSuggestionContext) -> object:
            nested: dict[str, object] = {field_name: "must be rejected"}
            state: dict[str, object]
            if container == "continuity_constraints":
                state = {container: [{"nested": nested}]}
            elif container == "video_reference_risk":
                state = {container: {"nested": nested}}
            else:
                state = {container: {"nested": nested}}
            return {
                "base_shot_version": shot.version,
                "suggested_image_prompt": "new image",
                "suggested_video_prompt": "new video",
                "suggested_director_state": state,
                "change_summary": "invalid field test",
            }

    with pytest.raises(ValidationAppError) as raised:
        await ShotDirectorSuggestionService(session, transport=InvalidTransport()).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot),
        )
    assert raised.value.details["code"] == "INVALID_DIRECTOR_SUGGESTION"
    assert shot.version == 5
    assert shot.image_prompt == "A cinematic keyframe"
    assert shot.video_prompt == "A slow turn toward the window"
    assert shot.director_state["workflow_template_key"] == "single-pass-v1"


@pytest.mark.asyncio
async def test_existing_design_extensions_are_preserved_in_valid_suggestion(
    session: AsyncSession,
) -> None:
    user, project, scene, shot = await _seed(session)
    result = await ShotDirectorSuggestionService(session).suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, shot),
    )
    assert result.suggested_director_state.root["workflow_template_key"] == "single-pass-v1"
    assert result.suggested_director_state.root["framing"] == {
        "shot_size": "medium",
        "angle": "eye_level",
    }
    assert shot.version == 5
    assert shot.image_prompt == "A cinematic keyframe"
    assert shot.video_prompt == "A slow turn toward the window"


def test_request_rejects_canonical_design_fields() -> None:
    with pytest.raises(ValueError):
        ShotDirectorSuggestionRequest.model_validate(
            {
                "scene_id": str(uuid4()),
                "shot_id": str(uuid4()),
                "expected_shot_version": 1,
                "user_instruction": "要求",
                "image_prompt": "客户端不得上传 canonical prompt",
            }
        )
