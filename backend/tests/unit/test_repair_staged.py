"""Staged, resumable repair workflow (DEV-06)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.delivery.models import ReviewAnnotation
from app.production.models import RepairRequest, RepairStep
from app.production.repair_service import RepairService
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.shared.security import hash_password
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


async def _seed(session: AsyncSession) -> tuple[Project, Shot, User]:
    user = User(
        email=f"staged-{uuid4().hex}@example.com",
        display_name="Repair",
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
    from app.execution.models import Artifact

    formal_keyframe = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="stored",
        object_key=f"obj/{uuid4().hex}",
        content_hash="f" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(formal_keyframe)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="Repair shot",
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
        formal_keyframe_artifact_id=formal_keyframe.id,
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


async def _annotation(
    session: AsyncSession, *, project: Project, shot: Shot, user: User, video_range: bool
) -> ReviewAnnotation:
    row = ReviewAnnotation(
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        time_start=2.3 if video_range else None,
        time_end=3.1 if video_range else None,
        x=None if video_range else 0.2,
        y=None if video_range else 0.3,
        width=None if video_range else 0.4,
        height=None if video_range else 0.2,
        note="drift",
        severity="warning",
        status="open",
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_model_infra(session: AsyncSession, *, project: Project, user: User) -> None:
    """Dispatch-capable workspace rows; shared with the other repair tests."""
    from model_infra_fixture import seed_model_infra

    await seed_model_infra(session, project=project, user=user)

async def _count(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


@pytest.mark.asyncio
async def test_plan_lists_the_staged_workflow_and_the_cost_boundary(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    await _annotation(session, project=project, shot=shot, user=user, video_range=True)

    plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)

    assert plan.steps == ["keyframe_regenerate", "keyframe_review", "video_rerun", "video_review"]
    assert plan.plan_schema_version == 1
    assert len(plan.plan_hash) == 64
    assert plan.annotation_ids
    # Cost is described, never quoted as a deterministic number.
    assert "不做确定性报价" in plan.cost_estimate_note
    assert "预算授权" in plan.cost_estimate_note


@pytest.mark.asyncio
async def test_create_repair_is_retry_safe_and_rejects_a_changed_plan(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    annotation = await _annotation(session, project=project, shot=shot, user=user, video_range=True)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)

    first = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="repair:one",
    )
    await session.flush()
    again = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="repair:one",
    )
    assert again.id == first.id
    assert await _count(session, RepairRequest) == 1

    # A plan previewed before the annotations changed is stale.
    annotation.status = "resolved"
    await session.flush()
    with pytest.raises(ConflictError) as stale:
        await service.create_repair(
            project=project,
            user=user,
            shot_id=shot.id,
            option="regenerate_keyframe_then_video",
            plan_hash=plan.plan_hash,
            request_key="repair:stale",
        )
    assert stale.value.details.get("code") == "REPAIR_PLAN_STALE"


@pytest.mark.asyncio
async def test_regenerate_stops_before_the_video_step_and_stays_resumable(
    session: AsyncSession,
) -> None:
    """Step 1 creates a candidate; the video step is not dispatched automatically."""
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    await _annotation(session, project=project, shot=shot, user=user, video_range=True)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="repair:staged",
    )
    await session.commit()

    request, step, run = await service.execute_step(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        idempotency_key="repair:staged:1",
    )
    await session.commit()

    assert step.ordinal == 1
    assert step.stage == "keyframe_regenerate"
    assert run.status == "queued"
    assert step.command_key == "repair:staged:1"
    assert (run.input_snapshot or {}).get("stage") == "image_keyframe"

    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    # Reopening the page shows the same repair and the next human step.
    assert state.next_action == "human_decision"
    assert [item.stage for item in state.steps] == ["keyframe_regenerate"]
    assert state.steps[0].node_run_id == run.id
    # The step has just been queued, so waiting on the server is the next action;
    # the candidate cannot be reviewed before the run produced it.
    assert state.steps[0].next_action == "wait"

    # The review step itself is a human decision, not a media action.
    with pytest.raises(ValidationAppError) as needs_review:
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
        )
    assert needs_review.value.details.get("code") == "REPAIR_STEP_REQUIRES_REVIEW"

    # Nothing replaced Formal or closed the annotations on its own.
    refreshed = await session.get(Shot, shot.id)
    assert refreshed is not None
    assert refreshed.formal_keyframe_artifact_id == shot.formal_keyframe_artifact_id


@pytest.mark.asyncio
async def test_rerun_video_is_one_step_and_never_touches_formal(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    await _annotation(session, project=project, shot=shot, user=user, video_range=False)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "rerun_video"

    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=plan.plan_hash,
        request_key="repair:video",
    )
    await session.commit()
    request, step, run = await service.execute_step(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
    )
    await session.commit()

    assert step.stage == "video_rerun"
    assert (run.input_snapshot or {}).get("stage") == "video"
    assert run.input_snapshot.get("workbench_plan", {}).get("expected_shot_version") == shot.version
    refreshed = await session.get(Shot, shot.id)
    assert refreshed is not None and refreshed.formal_video_artifact_id is None
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "human_decision"


@pytest.mark.asyncio
async def test_execute_step_needs_a_formal_keyframe_for_the_video_stage(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    shot.formal_keyframe_artifact_id = None
    await session.flush()
    await _annotation(session, project=project, shot=shot, user=user, video_range=False)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=plan.plan_hash,
        request_key="repair:nokey",
    )
    await session.flush()

    with pytest.raises(ValidationAppError) as missing:
        await service.execute_step(
            project=project, user=user, shot_id=shot.id, repair_id=request.id
        )
    assert missing.value.details.get("code") == "NO_FORMAL_KEYFRAME"
    assert await _count(session, RepairStep) == 0


@pytest.mark.asyncio
async def test_adopting_the_generated_candidate_links_it_back_to_the_step(
    session: AsyncSession,
) -> None:
    """A promotion records which repair step produced the adopted Artifact."""
    from app.execution.models import Artifact
    from app.production.repair_service import record_repair_adoption

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    await _annotation(session, project=project, shot=shot, user=user, video_range=True)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="repair:adopt",
    )
    await session.commit()
    request, step, run = await service.execute_step(
        project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    # The worker produced the candidate for this run.
    candidate = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(candidate)
    await session.flush()
    run.result_artifact_id = candidate.id
    await session.flush()

    updated = await record_repair_adoption(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=candidate.id,
        review_decision_id=uuid4(),
    )
    await session.flush()

    assert updated == 1
    stored = await session.get(RepairStep, step.id)
    assert stored is not None
    assert stored.adopted_artifact_id == candidate.id
    assert stored.review_decision_id is not None

    # Adopting an unrelated artifact changes nothing.
    other = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(other)
    await session.flush()
    assert (
        await record_repair_adoption(
            session, project_id=project.id, shot_id=shot.id, artifact_id=other.id
        )
        == 0
    )


@pytest.mark.asyncio
async def test_repairs_are_scoped_to_their_shot_and_project(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    other_project, other_shot, _other_user = await _seed(session)
    await _annotation(session, project=project, shot=shot, user=user, video_range=True)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="repair:scope",
    )
    await session.flush()

    listed = await service.list_repairs(project=project, shot_id=shot.id)
    assert [item.id for item in listed] == [request.id]
    assert await service.list_repairs(project=other_project, shot_id=other_shot.id) == []
    with pytest.raises(NotFoundError):
        await service.read_repair(
            project=other_project, shot_id=other_shot.id, repair_id=request.id
        )
