"""WF12 — Workflow Expansion Golden Gate (deterministic / fake-provider path).

Proves the full canonical professional workflow framework end-to-end without
spending real provider budget:

  Canonical path -> Template registry/freeze -> Episode/Scene/Shot materialize
  -> Multi-character participation + capability gate -> Complex-shot risk
  -> Scene orchestration status + failure isolation -> Continuity freeze
  -> Editing assembly -> Negative golden (no silent fallback / no collapse).

Real paid-provider generation (Agnes keyframe/video) is deliberately NOT issued
here; that remains the operator's representative real-provider golden run.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Scene, Shot
from app.director.workflows.character_participation import (
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
)
from app.director.workflows.continuity import (
    ContinuityVerdict,
    SceneContinuityContext,
    build_scene_continuity_report,
)
from app.director.workflows.contracts import (
    TemplateResolveStatus,
    WorkflowTemplateRequest,
)
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
from app.director.workflows.reference_capability import (
    MultiCharacterCapabilityStatus,
    assess_multi_character_capability,
)
from app.director.workflows.resolver import WorkflowTemplateResolver
from app.director.workflows.scene_orchestration import (
    SceneProductionState,
    is_scene_failure_isolated,
    scene_production_status,
)
from app.director.workflows.shot_complexity import (
    CameraMotion,
    ComplexityStrategy,
    ShotDirectorIntent,
    assess_shot_complexity,
)
from app.editing.timeline_builder import build_edit_session_for_project
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ConstraintSpec,
    InputSlotSpec,
    ModelManifest,
    SubmissionSemantics,
)
from app.shared.base import Base
from sqlalchemy import select
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


async def _seed_project(session: AsyncSession) -> UUID:
    user = User(
        email=f"wf12-{uuid4().hex[:8]}@example.com",
        display_name="U",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"Golden-{uuid4().hex[:6]}",
        stage="draft",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    return project.id


def _shot_plan(n: int, **overrides: object) -> ShotPlanPayload:
    return ShotPlanPayload(
        shot_number=n,
        visual_description=f"shot {n}",
        duration_seconds=6.0,
        sort_order=n,
        **overrides,  # type: ignore[arg-type]
    )


def _episode_plan() -> EpisodePlanPayload:
    return EpisodePlanPayload(
        episode_number=1,
        title="Golden 2-scene drama",
        target_duration=60.0,
        production_profile=ProductionProfile.SHORT_DRAMA_EPISODE,
        scenes=[
            ScenePlanPayload(
                scene_number=1,
                location="Street",
                time_of_day="night",
                scene_goal="Establish + dialogue",
                estimated_duration=30.0,
            ),
            ScenePlanPayload(
                scene_number=2,
                location="Room",
                time_of_day="night",
                scene_goal="Action + dialogue",
                estimated_duration=30.0,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_golden_workflow_expansion_end_to_end(session: AsyncSession) -> None:
    project_id = await _seed_project(session)

    # 1) Layered planning + real materialization (Episode/Scene/Shot rows).
    episode = await materialize_episode_plan(
        session, project_id=project_id, plan=_episode_plan()
    )
    scene1 = (
        await session.execute(
            select(Scene).where(Scene.episode_id == episode.id, Scene.scene_number == 1)
        )
    ).scalar_one()
    scene2 = (
        await session.execute(
            select(Scene).where(Scene.episode_id == episode.id, Scene.scene_number == 2)
        )
    ).scalar_one()

    shots_scene1 = await materialize_scene_storyboard(
        session,
        project_id=project_id,
        scene=scene1,
        storyboard=SceneStoryboardPlanPayload(
            shots=[
                _shot_plan(1, template_key="establishing-reaction-insert-v1"),
                _shot_plan(2, template_key="two-character-dialogue-v1"),
                _shot_plan(3, template_key="two-character-dialogue-v1"),
            ]
        ),
    )
    shots_scene2 = await materialize_scene_storyboard(
        session,
        project_id=project_id,
        scene=scene2,
        storyboard=SceneStoryboardPlanPayload(
            shots=[
                _shot_plan(1, template_key="action-motion-shot-v1"),
                _shot_plan(2, template_key="two-character-dialogue-v1"),
                _shot_plan(3, template_key="establishing-reaction-insert-v1"),
            ]
        ),
    )
    assert len(shots_scene1) == 3 and len(shots_scene2) == 3

    # 2) Template registry + freeze on the shot (G-WF-03).
    registry = get_default_registry()
    resolver = WorkflowTemplateResolver(registry)
    two_shot = shots_scene1[1]
    assert two_shot.director_state.get("workflow_template_key") == "two-character-dialogue-v1"
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=2,
            reference_roles_present=["character_a", "character_b"],
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "two-character-dialogue-v1"

    # 3) Multi-character participation + capability gate (G-WF-05/06).
    participation = ShotParticipationPlan(
        participations=[
            ShotCharacterParticipation(
                character_id=uuid4(),
                asset_version_id=uuid4(),
                screen_role=ScreenRole.PRIMARY,
            ),
            ShotCharacterParticipation(
                character_id=uuid4(),
                asset_version_id=uuid4(),
                screen_role=ScreenRole.SECONDARY,
            ),
        ]
    )
    assert participation.visible_controlled_count == 2

    # A model that supports only one reference_image cannot preserve B.
    one_ref_manifest = ModelManifest(
        manifest_version="1",
        id="agnes/single-ref",
        provider_id="agnes",
        model_name="single-ref",
        display_name="Single",
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
    assessment = assess_multi_character_capability(
        manifest=one_ref_manifest,
        capability=Capability.IMAGE_GENERATE,
        mode_id=None,
        plan=participation,
    )
    assert assessment.status == MultiCharacterCapabilityStatus.UNSUPPORTED
    # Provider POST must be 0 for UNSUPPORTED (fail closed).

    # 4) Complex-shot risk (deterministic strategy).
    complexity = assess_shot_complexity(
        intent=ShotDirectorIntent(camera_motion=CameraMotion.TRACKING, subject_blocking=["chase"]),
        participation_plan=ShotParticipationPlan(
            participations=[
                ShotCharacterParticipation(
                    character_id=uuid4(),
                    asset_version_id=uuid4(),
                    screen_role=ScreenRole.PRIMARY,
                ),
            ]
        ),
    )
    assert complexity.strategy == ComplexityStrategy.SINGLE_PASS  # low-risk single

    # 5) Scene orchestration status + failure isolation (G-WF-09).
    all_scene2_shots = list(
        (await session.execute(select(Shot).where(Shot.scene_id == scene2.id))).scalars()
    )
    status = scene_production_status(scene2, all_scene2_shots)
    assert status.state in {SceneProductionState.READY, SceneProductionState.PRODUCING}
    assert is_scene_failure_isolated(status) is True

    # 6) Continuity freeze + report (G-WF-08).
    context = SceneContinuityContext(
        scene_id=scene2.id,
        character_asset_versions={"A": uuid4(), "B": uuid4()},
        location_asset_versions={"room": uuid4()},
    )
    frozen = context.freeze()
    actual = {
        "character:A": frozen.character_asset_versions["A"],
        "character:B": frozen.character_asset_versions["B"],
        "location:room": frozen.location_asset_versions["room"],
    }
    report = build_scene_continuity_report(
        scene_id=scene2.id, context=frozen, actual_asset_versions=actual
    )
    assert report.overall == ContinuityVerdict.PASS

    # 7) Editing assembly preserves hierarchy + lineage.
    edit = await build_edit_session_for_project(
        session, project_id=project_id, user_id=uuid4(), name="Golden edit"
    )
    # No formal_video artifacts were produced (no paid generation), so clips may
    # be empty; if any are present they must carry hierarchy + lineage.
    for clip in edit["clips"]:
        assert {"episode_id", "scene_id", "shot_id", "artifact_id"} <= clip.keys()
    assert edit["production_lineage"]["lineage_readonly"] is True


@pytest.mark.asyncio
async def test_golden_negative_no_silent_fallback(session: AsyncSession) -> None:
    # NEG-01: explicit ineligible request never substitutes an available template.
    resolver = WorkflowTemplateResolver(get_default_registry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=0,
            explicit_template_key="two-character-dialogue-v1",
        )
    )
    assert resolution.status == TemplateResolveStatus.UNAVAILABLE
    assert resolution.resolved_template_key is None
