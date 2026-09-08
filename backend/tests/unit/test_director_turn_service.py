"""R4a durable Director turn lifecycle, bounds, and recovery."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.text_transport import DirectorTextTransport
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.execution.models import NodeRun
from app.shared.base import Base
from app.shared.errors import ConflictError, ValidationAppError
from app.shared.security import hash_password
from app.workbench.shot_service import ShotDesignService
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


async def _seed(session: AsyncSession) -> tuple[Project, User, Shot]:
    user = User(
        email=f"turn-{uuid4().hex}@example.com",
        display_name="Turn owner",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        budget_limit=0,
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
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="A saved shot",
        image_prompt="saved image prompt",
        video_prompt="saved video prompt",
    )
    session.add(shot)
    await session.flush()
    return project, user, shot


@pytest.mark.asyncio
async def test_create_is_idempotent_and_claim_is_revision_atomic(session: AsyncSession) -> None:
    project, user, shot = await _seed(session)
    service = DirectorTurnService(session)
    context = {"shot_id": str(shot.id), "shot_version": shot.version}
    turn, created = await service.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:one",
        context_snapshot=context,
        input_versions={"shot": shot.version},
        intent_snapshot={"goal": "analyze saved shot"},
        max_steps=2,
    )
    replay, replay_created = await service.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:one",
        context_snapshot=context,
    )
    assert created is True
    assert replay_created is False
    assert replay.id == turn.id
    with pytest.raises(ConflictError) as reused:
        await service.create_or_get(
            project=project,
            actor=user,
            scope_type="shot",
            scope_entity_id=shot.id,
            request_key="director-cycle:one",
            context_snapshot={**context, "shot_version": shot.version + 1},
        )
    assert reused.value.details["code"] == "DIRECTOR_REQUEST_KEY_REUSED"

    claimed = await service.claim(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=turn.revision,
    )
    assert claimed.status == "thinking"
    assert claimed.step_count == 1
    assert claimed.revision == 2
    with pytest.raises(ConflictError) as duplicate_claim:
        await service.claim(
            project_id=project.id,
            turn_id=turn.id,
            expected_revision=1,
        )
    assert duplicate_claim.value.details["code"] == "DIRECTOR_TURN_CLAIM_CONFLICT"


@pytest.mark.asyncio
async def test_recovery_fails_unknown_text_submission_once_without_media_write(
    session: AsyncSession,
) -> None:
    project, user, shot = await _seed(session)
    service = DirectorTurnService(session)
    turn, _ = await service.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:unknown",
        context_snapshot={"shot_version": shot.version},
    )
    await service.claim(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=turn.revision,
    )
    await service.compare_and_set(
        turn=turn,
        expected_statuses=("thinking",),
        target_status="thinking",
        updates={"transport_status": "submission_started", "wait_reason": "text_model"},
    )

    recovered = await service.recover_interrupted(
        project_id=project.id,
        turn_id=turn.id,
    )
    recovered_revision = recovered.revision
    assert recovered.status == "failed"
    assert recovered.transport_status == "unknown_submission"
    assert recovered.wait_reason == "text_submission_unknown"
    assert "automatic replay is forbidden" in str(recovered.last_error)
    second = await service.recover_interrupted(project_id=project.id, turn_id=turn.id)
    assert second.revision == recovered_revision
    assert (await session.execute(select(NodeRun))).scalars().all() == []


@pytest.mark.asyncio
async def test_deadline_and_step_limit_are_readable_terminal_stops(session: AsyncSession) -> None:
    project, user, shot = await _seed(session)
    service = DirectorTurnService(session)
    expired, _ = await service.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:expired",
        context_snapshot={"kind": "expired"},
        deadline=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(ConflictError) as deadline_error:
        await service.claim(
            project_id=project.id,
            turn_id=expired.id,
            expected_revision=expired.revision,
        )
    assert deadline_error.value.details["wait_reason"] == "deadline_exceeded"
    await session.refresh(expired)
    assert expired.status == "failed"

    exhausted = DirectorTurn(
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:exhausted",
        context_hash="f" * 64,
        request_summary={"max_steps": 1},
        status="queued",
        step_count=1,
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(exhausted)
    await session.flush()
    with pytest.raises(ConflictError) as step_error:
        await service.claim(
            project_id=project.id,
            turn_id=exhausted.id,
            expected_revision=exhausted.revision,
        )
    assert step_error.value.details["wait_reason"] == "step_limit_reached"


@pytest.mark.asyncio
async def test_user_shot_save_marks_active_turn_stale_and_late_state_cannot_revive(
    session: AsyncSession,
) -> None:
    project, user, shot = await _seed(session)
    turns = DirectorTurnService(session)
    turn, _ = await turns.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:user-edit",
        context_snapshot={"shot_version": shot.version},
    )
    await turns.claim(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=turn.revision,
    )
    updated = await ShotDesignService(session).update_shot_design(
        project_id=project.id,
        shot_id=shot.id,
        actor=user,
        expected_version=shot.version,
        video_prompt="new user-owned video prompt",
    )
    await session.refresh(turn)
    assert updated.video_prompt == "new user-owned video prompt"
    assert turn.status == "stale"
    assert turn.wait_reason == "context_changed"
    with pytest.raises(ValidationAppError):
        await DirectorTextTransport(session).mark_awaiting_user(turn)
    await session.refresh(turn)
    assert turn.status == "stale"
    assert updated.video_prompt == "new user-owned video prompt"


@pytest.mark.asyncio
async def test_stop_and_read_preserve_links_and_do_not_cancel_media(session: AsyncSession) -> None:
    project, user, shot = await _seed(session)
    service = DirectorTurnService(session)
    turn, _ = await service.create_or_get(
        project=project,
        actor=user,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key="director-cycle:stop",
        context_snapshot={"shot_version": shot.version},
    )
    turn.node_run_ids = [str(uuid4())]
    turn.dispatched_command_key = "workbench:existing-command"
    await session.flush()
    stopped = await service.stop(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=turn.revision,
    )
    assert stopped.status == "cancelled"
    assert stopped.wait_reason == "user_stopped"
    assert stopped.node_run_ids == turn.node_run_ids
    listed = await service.list(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
    )
    assert [row.id for row in listed] == [turn.id]
    same = await service.stop(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=stopped.revision,
    )
    assert same.revision == stopped.revision


def test_default_worker_registers_director_restart_recovery() -> None:
    from app.workers.default import WorkerSettings
    from app.workers.jobs import (
        JOB_FUNCTIONS,
        reconcile_waiting_director_turns,
        recover_interrupted_director_turns,
    )

    assert recover_interrupted_director_turns in JOB_FUNCTIONS
    assert reconcile_waiting_director_turns in JOB_FUNCTIONS
    assert WorkerSettings.on_startup is recover_interrupted_director_turns
    assert [job.coroutine for job in WorkerSettings.cron_jobs] == [
        reconcile_waiting_director_turns
    ]
