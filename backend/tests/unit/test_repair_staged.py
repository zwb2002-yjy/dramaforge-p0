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
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from repair_fixture import approve_and_adopt


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
        storage_state="available",
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

    request, step, run = await _previewed_step(
        service,
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
    assert state.next_action == "wait"
    assert [item.stage for item in state.steps] == ["keyframe_regenerate"]
    assert state.steps[0].node_run_id == run.id
    # The step has just been queued, so waiting on the server is the next action;
    # the candidate cannot be reviewed before the run produced it.
    assert state.steps[0].next_action == "wait"
    assert state.steps[0].result_artifact_id is None

    # Completed candidate B must be readable before any Formal adoption;
    # it is not the Shot's existing formal A or an adopted-artifact pointer.
    from app.execution.models import Artifact

    candidate = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="stored",
        object_key=f"candidate/{uuid4().hex}",
        content_hash="b" * 64,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(candidate)
    await session.flush()
    run.result_artifact_id = candidate.id
    run.status = "completed"
    await session.flush()
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.steps[0].result_artifact_id == candidate.id
    assert state.steps[0].adopted_artifact_id is None
    assert state.steps[0].result_artifact_id != shot.formal_keyframe_artifact_id

    # The review step itself is a human decision, not a media action.
    with pytest.raises(ValidationAppError) as needs_review:
        await _previewed_step(
            service,
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
    request, step, run = await _previewed_step(
        service,
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
    assert state.next_action == "wait"


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
        await _previewed_step(
            service, project=project, user=user, shot_id=shot.id, repair_id=request.id
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
    request, step, run = await _previewed_step(
        service, project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    candidate, decision = await approve_and_adopt(
        session,
        project=project,
        shot=shot,
        user=user,
        run=run,
    )
    stored = await session.get(RepairStep, step.id)
    assert stored is not None
    assert stored.adopted_artifact_id == candidate.id
    assert stored.review_decision_id == decision.id

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


async def _previewed_step(
    service,
    *,
    project,
    user,
    shot_id,
    repair_id,
    idempotency_key="test-step",
):
    preview = await service.build_step_plan(
        project=project,
        user=user,
        shot_id=shot_id,
        repair_id=repair_id,
    )
    return await service.execute_step(
        project=project,
        user=user,
        shot_id=shot_id,
        repair_id=repair_id,
        expected_plan_fingerprint=preview.plan.plan_fingerprint,
        expected_step_ordinal=preview.step_ordinal,
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_approved_keyframe_resumes_to_video_and_final_adoption_can_close(session):
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    plan = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=plan.plan_hash,
        request_key="continuity",
    )
    _, first, image_run = await _previewed_step(
        service,
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        idempotency_key="image",
    )
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "wait"
    image, decision = await approve_and_adopt(
        session,
        project=project,
        shot=shot,
        user=user,
        run=image_run,
    )
    # Simulate reopening: no in-memory progress token, only persisted facts.
    service = RepairService(session)
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "execute_step"
    assert state.next_step_ordinal == 3
    assert state.steps[0].review_decision_id == decision.id
    _, second, video_run = await _previewed_step(
        service,
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        idempotency_key="video",
    )
    assert second.ordinal == 3
    assert second.id != first.id
    assert any(
        ref["artifact_id"] == str(image.id)
        for ref in video_run.input_snapshot["workbench_plan"]["planned_references"]
    )
    await approve_and_adopt(
        session, project=project, shot=shot, user=user, run=video_run, video=True
    )
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "ready_to_close"
    await service.close_repair(
        project=project, shot_id=shot.id, repair_id=request.id, reason="completed"
    )
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "closed"
    assert state.closed_reason == "completed"
    shot.formal_video_artifact_id = None  # a subsequent production revision
    await session.flush()
    history = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert history.next_action == "closed"
    assert all(item.next_action == "adopted" for item in history.steps)


@pytest.mark.asyncio
async def test_repair_first_step_checks_preview_and_lost_response_reuses_receipt(session):
    from app.execution.models import NodeRun

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="receipt",
    )
    preview = await service.build_step_plan(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
    )
    assert await _count(session, NodeRun) == 0
    shot.image_prompt = "A deliberately changed saved prompt"
    shot.version += 1
    await session.flush()
    with pytest.raises(ConflictError) as stale:
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
            expected_step_ordinal=1,
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            idempotency_key="lost-response",
        )
    assert stale.value.details["code"] == "REPAIR_STEP_PLAN_MISMATCH"
    assert await _count(session, NodeRun) == 0
    fresh = await service.build_step_plan(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
    )
    payload = dict(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        expected_step_ordinal=1,
        expected_plan_fingerprint=fresh.plan.plan_fingerprint,
        idempotency_key="lost-response",
    )
    _, first, run = await service.execute_step(**payload)
    count = await _count(session, NodeRun)
    await session.commit()
    shot.version += 1
    shot.image_prompt = "Mutable settings changed after dispatch"
    await session.flush()
    _, repeated, same_run = await RepairService(session).execute_step(**payload)
    assert repeated.id == first.id
    assert same_run.id == run.id
    assert await _count(session, NodeRun) == count
    with pytest.raises(ConflictError) as reused:
        await service.execute_step(**{**payload, "expected_step_ordinal": 3})
    assert reused.value.details["code"] == "REPAIR_COMMAND_REUSED"
    with pytest.raises(ConflictError) as active:
        await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="abandoned"
        )
    assert active.value.details["code"] == "REPAIR_RUN_ACTIVE"


@pytest.mark.asyncio
async def test_repair_preserves_saved_references_and_detects_binding_change(session):
    from app.execution.models import Artifact, NodeRun
    from app.production.models import ShotReferenceBinding

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    reference = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"ref/{uuid4().hex}",
        content_hash="1" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(reference)
    await session.flush()
    binding = ShotReferenceBinding(
        project_id=project.id,
        shot_id=shot.id,
        stage="image",
        purpose="identity",
        artifact_id=reference.id,
        resolution_mode="direct_artifact",
        created_by=user.id,
    )
    session.add(binding)
    await session.flush()
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="refs",
    )
    preview = await service.build_step_plan(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
    )
    assert len(preview.plan.planned_references) == 1
    assert preview.plan.planned_references[0].artifact_id == reference.id
    assert preview.plan.planned_references[0].binding_id == binding.id
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        await other.execute(
            update(ShotReferenceBinding)
            .where(
                ShotReferenceBinding.id == binding.id,
            )
            .values(artifact_id=shot.formal_keyframe_artifact_id)
        )
        await other.commit()
    with pytest.raises(ConflictError) as stale:
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
            expected_step_ordinal=1,
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            idempotency_key="refs-step",
        )
    assert stale.value.details["code"] == "REPAIR_STEP_PLAN_MISMATCH"
    assert await _count(session, NodeRun) == 0


@pytest.mark.asyncio
async def test_repair_does_not_adopt_unreviewed_candidates_or_dispatch_after_failure(session):
    from app.execution.models import Artifact
    from app.production.repair_service import record_repair_adoption

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="unreviewed",
    )
    _, step, run = await _previewed_step(
        service, project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    candidate = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"candidate/{uuid4().hex}",
        content_hash="2" * 64,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(candidate)
    await session.flush()
    run.result_artifact_id = candidate.id
    run.status = "completed"
    await session.flush()
    assert (
        await record_repair_adoption(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=candidate.id,
            review_decision_id=uuid4(),
        )
        == 0
    )
    assert step.adopted_artifact_id is None
    with pytest.raises(ConflictError) as incomplete:
        await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="completed"
        )
    assert incomplete.value.details["code"] == "REPAIR_NOT_COMPLETE"
    run.status = "failed"
    run.error_code = "PROVIDER_SUBMISSION_UNKNOWN"
    run.result_artifact_id = None
    await session.flush()
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "reconcile_submission"
    assert state.steps[0].node_run_error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    with pytest.raises(ConflictError):
        await service.build_step_plan(
            project=project, user=user, shot_id=shot.id, repair_id=request.id
        )
    with pytest.raises(ConflictError) as unknown:
        await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="abandoned"
        )
    assert unknown.value.details["code"] == "REPAIR_SUBMISSION_UNKNOWN"
    assert request.closed_reason is None
    with pytest.raises(ConflictError) as active:
        fresh = await service.build_repair_plan(project=project, shot_id=shot.id)
        await service.create_repair(
            project=project,
            user=user,
            shot_id=shot.id,
            option="rerun_video",
            plan_hash=fresh.plan_hash,
            request_key="do-not-repay",
        )
    assert active.value.details["code"] == "REPAIR_ALREADY_ACTIVE"
    assert await _count(session, RepairStep) == 1
    assert run.status == "failed"


def test_repair_http_execution_requires_both_frozen_plan_and_step():
    from app.api.v1.workbench import RepairStepExecuteBody
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepairStepExecuteBody(idempotency_key="unsafe")
    with pytest.raises(ValidationError):
        RepairStepExecuteBody(expected_plan_fingerprint="a" * 64, idempotency_key="unsafe")


@pytest.mark.asyncio
async def test_approximate_references_need_an_explicit_new_preview_before_dispatch(session):
    from app.production.models import ShotReferenceBinding

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    session.add(
        ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            stage="image",
            purpose="style",
            artifact_id=shot.formal_keyframe_artifact_id,
            resolution_mode="direct_artifact",
            created_by=user.id,
        )
    )
    await session.flush()
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="style-repair",
    )
    preview = await service.build_step_plan(
        project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    assert preview.plan.capability_gaps
    assert all(gap.severity == "warning" for gap in preview.plan.capability_gaps)
    assert not preview.plan.accepted_approximations
    with pytest.raises(ValidationAppError):
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
            expected_step_ordinal=1,
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            idempotency_key="style-step",
        )
    accepted = await service.build_step_plan(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        accept_approximations=True,
    )
    assert accepted.plan.accepted_approximations
    assert not accepted.plan.capability_gaps
    assert accepted.plan.plan_fingerprint != preview.plan.plan_fingerprint
    with pytest.raises(ConflictError):
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
            expected_step_ordinal=1,
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            accept_approximations=True,
            idempotency_key="style-step",
        )
    _, _, run = await service.execute_step(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_id=request.id,
        expected_step_ordinal=1,
        expected_plan_fingerprint=accepted.plan.plan_fingerprint,
        accept_approximations=True,
        idempotency_key="style-step",
    )
    assert run.input_snapshot["workbench_plan"]["accepted_approximations"]


@pytest.mark.asyncio
async def test_asset_formal_changed_in_another_session_invalidates_repair_preview(session):
    from app.assets.models import Asset, AssetVersion, AssetVersionReference
    from app.execution.models import Artifact
    from app.production.models import ShotReferenceBinding

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    asset = Asset(project_id=project.id, kind="character", name="Hero", status="active")
    session.add(asset)
    await session.flush()
    versions = []
    for number in (1, 2):
        version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=number,
            kind="character",
            name=f"Hero {number}",
            status="formal",
            created_by=user.id,
        )
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            storage_state="available",
            object_key=f"hero/{uuid4().hex}",
            content_hash=str(number) * 64,
            mime_type="image/png",
            byte_size=1,
        )
        session.add_all([version, artifact])
        await session.flush()
        session.add(
            AssetVersionReference(
                project_id=project.id,
                asset_version_id=version.id,
                artifact_id=artifact.id,
                reference_role="front_face",
            )
        )
        versions.append(version)
    asset.current_version_id = versions[0].id
    session.add(
        ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            asset_id=asset.id,
            stage="image",
            purpose="identity",
            resolution_mode="current_formal",
            created_by=user.id,
        )
    )
    await session.flush()
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="asset-cache",
    )
    preview = await service.build_step_plan(
        project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        await other.execute(
            update(Asset).where(Asset.id == asset.id).values(current_version_id=versions[1].id)
        )
        await other.commit()
    assert asset.current_version_id == versions[0].id  # A intentionally holds stale ORM state.
    with pytest.raises(ConflictError) as stale:
        await service.execute_step(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_id=request.id,
            expected_step_ordinal=1,
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            idempotency_key="asset-step",
        )
    assert stale.value.details["code"] == "REPAIR_STEP_PLAN_MISMATCH"
    assert await _count(session, RepairStep) == 0


@pytest.mark.asyncio
async def test_close_refreshes_formal_facts_changed_by_another_session(session):
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=intent.plan_hash,
        request_key="close-cache",
    )
    _, _, run = await _previewed_step(
        service, project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    candidate, _ = await approve_and_adopt(
        session, project=project, shot=shot, user=user, run=run, video=True
    )
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        await other.execute(
            update(Shot)
            .where(Shot.id == shot.id)
            .values(formal_video_artifact_id=None, version=shot.version + 1)
        )
        await other.commit()
    assert shot.formal_video_artifact_id == candidate.id
    with pytest.raises(ConflictError) as stale:
        await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="completed"
        )
    assert stale.value.details["code"] == "REPAIR_NOT_COMPLETE"
    assert request.closed_reason is None


@pytest.mark.asyncio
async def test_abandoned_unsubmitted_repair_does_not_block_the_next_production_revision(session):
    project, shot, user = await _seed(session)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    first = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=intent.plan_hash,
        request_key="first",
    )
    await service.close_repair(
        project=project, shot_id=shot.id, repair_id=first.id, reason="abandoned"
    )
    second = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=intent.plan_hash,
        request_key="second",
    )
    assert second.id != first.id
    assert second.closed_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize("video", [False, True], ids=["resume-video", "close-video"])
async def test_repair_refreshes_run_completed_in_another_session(session, video):
    from app.execution.models import NodeRun

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video" if video else "regenerate_keyframe_then_video",
        plan_hash=intent.plan_hash,
        request_key="external-completion",
    )
    _, _, held_run = await _previewed_step(
        service, project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        other_project = await other.get(Project, project.id)
        other_shot = await other.get(Shot, shot.id)
        other_user = await other.get(User, user.id)
        other_run = await other.get(NodeRun, held_run.id)
        assert all(row is not None for row in (other_project, other_shot, other_user, other_run))
        candidate, decision = await approve_and_adopt(
            other,
            project=other_project,
            shot=other_shot,
            user=other_user,
            run=other_run,
            video=video,
        )

    # Keep A's actual queued ORM object alive while B commits worker/review facts.
    assert held_run.status == "queued"
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == ("ready_to_close" if video else "execute_step")
    assert state.steps[0].node_run_status == "completed"
    assert state.steps[0].result_artifact_id == candidate.id
    assert state.steps[0].review_decision_id == decision.id
    if video:
        closed = await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="completed"
        )
        assert closed.next_action == "closed"
    else:
        preview = await service.build_step_plan(
            project=project, user=user, shot_id=shot.id, repair_id=request.id
        )
        assert preview.step_ordinal == 3
        assert preview.stage == "video_rerun"
    assert await _count(session, RepairStep) == 1


@pytest.mark.asyncio
async def test_repair_refreshes_unknown_submission_before_close(session):
    from app.execution.models import NodeRun

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    service = RepairService(session)
    intent = await service.build_repair_plan(project=project, shot_id=shot.id)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        option="rerun_video",
        plan_hash=intent.plan_hash,
        request_key="external-unknown",
    )
    _, _, held_run = await _previewed_step(
        service, project=project, user=user, shot_id=shot.id, repair_id=request.id
    )
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        await other.execute(
            update(NodeRun)
            .where(NodeRun.id == held_run.id)
            .values(status="failed", error_code="PROVIDER_SUBMISSION_UNKNOWN")
        )
        await other.commit()

    assert held_run.status == "queued"
    assert held_run.error_code is None
    with pytest.raises(ConflictError) as unknown:
        await service.close_repair(
            project=project, shot_id=shot.id, repair_id=request.id, reason="abandoned"
        )
    assert unknown.value.details["code"] == "REPAIR_SUBMISSION_UNKNOWN"
    state = await service.read_repair(project=project, shot_id=shot.id, repair_id=request.id)
    assert state.next_action == "reconcile_submission"
    assert state.steps[0].node_run_error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert state.closed_reason is None
    assert await _count(session, RepairStep) == 1
