"""WF13 — workflow planning freeze API + wire-visible read models."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Scene
from app.director.workflows.contracts import TemplateResolveStatus, WorkflowTemplateRequest
from app.director.workflows.layered_planning import (
    EpisodePlanPayload,
    ProductionProfile,
    ScenePlanPayload,
    SceneStoryboardPlanPayload,
    ShotPlanPayload,
)
from app.director.workflows.layered_production_service import (
    materialize_episode_plan,
    materialize_scene_storyboard,
)
from app.director.workflows.library import get_default_registry
from app.director.workflows.resolver import WorkflowTemplateResolver
from app.director.workflows.workflow_read_models import (
    build_project_workflow_overview,
    build_shot_workflow_state,
)
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ConstraintSpec,
    InputSlotSpec,
    ModelManifest,
    SubmissionSemantics,
)
from sqlalchemy import select


@pytest.fixture
async def session():
    from app.shared.base import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_project(session) -> Project:
    user = User(email=f"wf13-{uuid4().hex[:8]}@example.com", display_name="U", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"WF13-{uuid4().hex[:6]}",
        stage="draft",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    return project


def _one_ref_manifest() -> ModelManifest:
    return ModelManifest(
        manifest_version="1",
        id="m/one-ref",
        provider_id="agnes",
        model_name="one-ref",
        display_name="OneRef",
        capability_specs={
            Capability.IMAGE_GENERATE: CapabilitySpec(
                capability=Capability.IMAGE_GENERATE,
                transport_profile_id="t1",
                input_slots={
                    "reference_image": InputSlotSpec(
                        minimum=0, maximum=1, media_types=["image/*"]
                    ),
                },
                constraints=ConstraintSpec(),
            ),
        },
        execution_mode="sync",
        submission_semantics=SubmissionSemantics(),
    )


def _episode_plan_payload() -> EpisodePlanPayload:
    return EpisodePlanPayload(
        episode_number=1,
        title="WF13 state",
        target_duration=60.0,
        production_profile=ProductionProfile.SHORT_DRAMA_EPISODE,
        scenes=[
            ScenePlanPayload(
                scene_number=1,
                location="Street",
                time_of_day="night",
                scene_goal="establish + dialogue",
                estimated_duration=30.0,
            ),
            ScenePlanPayload(
                scene_number=2,
                location="Room",
                time_of_day="night",
                scene_goal="action",
                estimated_duration=30.0,
            ),
        ],
    )


def _scene_query(episode_id, number: int):
    return select(Scene).where(Scene.episode_id == episode_id, Scene.scene_number == number)


def _storyboard(specs: list[dict[str, object]]) -> SceneStoryboardPlanPayload:
    return SceneStoryboardPlanPayload(
        shots=[
            ShotPlanPayload(
                shot_number=int(s["shot_number"]),
                visual_description=str(s["visual_description"]),
                duration_seconds=6.0,
                sort_order=int(s["shot_number"]),
                template_key=s.get("template_key"),  # type: ignore[arg-type]
            )
            for s in specs
        ]
    )


@pytest.mark.asyncio
async def test_shot_workflow_state_reports_frozen_template(session) -> None:
    project = await _seed_project(session)
    episode = await materialize_episode_plan(
        session, project_id=project.id, plan=_episode_plan_payload()
    )
    scene1 = (await session.execute(_scene_query(episode.id, 1))).scalar_one()
    shots = await materialize_scene_storyboard(
        session,
        project_id=project.id,
        scene=scene1,
        storyboard=_storyboard(
            [
                {"shot_number": 1, "visual_description": "establishing"},
                {
                    "shot_number": 2,
                    "visual_description": "two characters argue",
                    "template_key": "two-character-dialogue-v1",
                },
            ]
        ),
    )
    await session.flush()

    state = build_shot_workflow_state(shot=shots[1], episode_id=episode.id)
    assert state.workflow_template_key == "two-character-dialogue-v1"
    assert state.template_resolution_status == "RESOLVED"
    assert state.template_contract_hash is not None
    assert state.quality_policy_id == "two-character-dialogue-quality-v1"
    # No participations frozen yet -> no assessment.
    assert state.capability_assessment is None

    # Un-frozen shot reports honest NONE, never an auto-substituted template.
    other = build_shot_workflow_state(shot=shots[0], episode_id=episode.id)
    assert other.workflow_template_key is None
    assert other.template_resolution_status == "NONE"


@pytest.mark.asyncio
async def test_frozen_unknown_template_reads_unavailable(session) -> None:
    """A frozen key that later disappears from the registry must not lie."""
    project = await _seed_project(session)
    episode = await materialize_episode_plan(
        session, project_id=project.id, plan=_episode_plan_payload()
    )
    scene1 = (await session.execute(_scene_query(episode.id, 1))).scalar_one()
    shots = await materialize_scene_storyboard(
        session,
        project_id=project.id,
        scene=scene1,
        storyboard=_storyboard([{"shot_number": 1, "visual_description": "x"}]),
    )
    shots[0].director_state = {"workflow_template_key": "removed-template-v1"}
    await session.flush()

    state = build_shot_workflow_state(shot=shots[0], episode_id=episode.id)
    assert state.template_resolution_status == "UNAVAILABLE"
    assert state.template_version is None


def test_explicit_two_character_template_still_resolves_for_planning() -> None:
    """Planning resolution is independent of the per-model capability gate.

    The gate (UNSUPPORTED / POST=0) is deterministic on the *manifest*; the
    template resolver must keep resolving the explicitly frozen identity so the
    UI can show what was chosen alongside why paid dispatch is blocked.
    """
    registry = get_default_registry()
    resolver = WorkflowTemplateResolver(registry)
    spec = registry.get("two-character-dialogue-v1")
    assert spec is not None
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=list(spec.intent_tags),
            medium="video",
            character_count=2,
            reference_roles_present=list(spec.required_reference_roles),
            explicit_template_key="two-character-dialogue-v1",
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED


@pytest.mark.asyncio
async def test_project_overview_counts_and_unsupported(session) -> None:
    from app.director.workflows.character_participation import (
        ScreenRole,
        ShotCharacterParticipation,
        ShotParticipationPlan,
        participation_director_state,
    )

    project = await _seed_project(session)
    episode = await materialize_episode_plan(
        session, project_id=project.id, plan=_episode_plan_payload()
    )
    scenes = (
        (
            await session.execute(select(Scene).where(Scene.episode_id == episode.id))
        )
        .scalars()
        .all()
    )
    by_number = {s.scene_number: s for s in scenes}
    shots_s1 = await materialize_scene_storyboard(
        session,
        project_id=project.id,
        scene=by_number[1],
        storyboard=_storyboard([{"shot_number": 1, "visual_description": "a"}]),
    )
    shots_s2 = await materialize_scene_storyboard(
        session,
        project_id=project.id,
        scene=by_number[2],
        storyboard=_storyboard([{"shot_number": 1, "visual_description": "b"}]),
    )
    # Freeze a two-visible-character plan onto scene2's only shot.
    plan = ShotParticipationPlan(
        participations=[
            ShotCharacterParticipation(
                asset_id=uuid4(), asset_version_id=uuid4(), screen_role=ScreenRole.PRIMARY
            ),
            ShotCharacterParticipation(
                asset_id=uuid4(), asset_version_id=uuid4(), screen_role=ScreenRole.SECONDARY
            ),
        ]
    )
    shots_s2[0].director_state = participation_director_state(plan)
    await session.flush()

    overview = build_project_workflow_overview(
        project_id=project.id,
        scenes=[(episode, s) for s in sorted(scenes, key=lambda x: x.scene_number)],
        shots_by_scene={by_number[1].id: list(shots_s1), by_number[2].id: list(shots_s2)},
        manifests_by_scene={by_number[2].id: _one_ref_manifest()},
    )
    assert overview.total_shots == 2
    assert overview.formal_shots == 0
    assert overview.blocked_scenes == 0
    # One scene carries UNSUPPORTED capability for its 2-subject requirement.
    assert overview.unsupported_capability_shots == 1
