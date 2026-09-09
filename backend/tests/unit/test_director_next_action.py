"""R4b finite, fact-derived Director next-action reconciliation."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.access.models import Project, ProjectCreativeProfile, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.assistant_models import DirectorThread
from app.director.next_action import DirectorNextAction, DirectorNextActionService
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.execution.shot_pipeline import SHOT_PIPELINE_TEMPLATE_KEY, shot_pipeline_definition
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.errors import ConflictError, ValidationAppError
from app.shared.security import hash_password
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


async def _seed(
    session: AsyncSession,
    *,
    autonomy: str = "ASSIST",
) -> tuple[Project, User, Shot, NodeRun, DirectorTurn]:
    user = User(
        email=f"next-{uuid4().hex}@example.com",
        display_name="Next action",
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
    session.add(
        ProjectCreativeProfile(
            project_id=project.id,
            start_type="FREE",
            director_autonomy=autonomy,
        )
    )
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
        visual_description="A shot",
    )
    session.add(shot)
    await session.flush()
    graphs = GraphService(session)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key=SHOT_PIPELINE_TEMPLATE_KEY,
        created_by=user.id,
        definition=shot_pipeline_definition(shot_id=str(shot.id)),
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = await graphs.publish(version_id=materialized.version.id, published_by=user.id)
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=materialized.nodes["keyframe"].id,
        idempotency_key=f"next:{uuid4().hex}",
        input_hash="a" * 64,
        status="running",
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    turn = DirectorTurn(
        workspace_id=workspace.id,
        project_id=project.id,
        actor_id=user.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key=f"next-turn:{uuid4().hex}",
        context_hash="b" * 64,
        request_summary={"max_steps": 4},
        status="awaiting_execution",
        wait_reason="execution",
        node_run_ids=[str(run.id)],
        step_count=1,
    )
    session.add(turn)
    await session.flush()
    return project, user, shot, run, turn


@pytest.mark.asyncio
async def test_active_execution_deduplicates_by_fact_set_then_assist_reviews_terminal_result(
    session: AsyncSession,
) -> None:
    project, user, shot, run, turn = await _seed(session, autonomy="ASSIST")
    service = DirectorNextActionService(session)
    first = await service.reconcile(
        project=project,
        turn_id=turn.id,
        event_key="execution:event:one",
        expected_revision=turn.revision,
    )
    assert first.action is DirectorNextAction.WAIT_FOR_EXECUTION
    assert first.requires_confirmation is False
    assert turn.status == "awaiting_execution"
    first_revision = turn.revision
    first_step = turn.step_count

    duplicate = await service.reconcile(
        project=project,
        turn_id=turn.id,
        event_key="execution:event:duplicate-key",
        expected_revision=1,
    )
    assert duplicate.fact_hash == first.fact_hash
    assert turn.revision == first_revision
    assert turn.step_count == first_step

    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="c" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(artifact)
    await session.flush()
    run.status = "completed"
    run.result_artifact_id = artifact.id
    await session.flush()
    terminal = await service.reconcile(project=project, turn_id=turn.id)
    assert terminal.action is DirectorNextAction.REVIEW_PRODUCTION_RESULT
    assert terminal.requires_confirmation is True
    assert turn.status == "awaiting_user"
    assert turn.wait_reason == "production_review"
    stable_revision = turn.revision
    repeated = await service.reconcile(project=project, turn_id=turn.id)
    assert repeated == terminal
    assert turn.revision == stable_revision
    assert shot.formal_keyframe_artifact_id is None
    assert (await session.execute(select(ProviderOperation))).scalars().all() == []
    assert len((await session.execute(select(NodeRun))).scalars().all()) == 1
    _ = user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("autonomy", "expected"),
    [
        ("AUTO", DirectorNextAction.CONFIRM_FORMAL_CANDIDATE),
        ("MANUAL", DirectorNextAction.MANUAL_NO_ADVANCE),
    ],
)
async def test_terminal_action_depends_on_current_autonomy_without_formal_promotion(
    session: AsyncSession,
    autonomy: str,
    expected: DirectorNextAction,
) -> None:
    project, _user, shot, run, turn = await _seed(session, autonomy=autonomy)
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="e" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(artifact)
    await session.flush()
    run.status = "completed"
    run.result_artifact_id = artifact.id
    result = await DirectorNextActionService(session).reconcile(
        project=project,
        turn_id=turn.id,
    )
    assert result.action is expected
    assert result.requires_confirmation is True
    assert shot.formal_keyframe_artifact_id is None
    repeated = await DirectorNextActionService(session).reconcile(
        project=project, turn_id=turn.id
    )
    assert repeated == result


@pytest.mark.asyncio
async def test_failed_execution_and_missing_link_fail_closed(session: AsyncSession) -> None:
    project, _user, _shot, run, turn = await _seed(session)
    run.status = "failed"
    result = await DirectorNextActionService(session).reconcile(
        project=project,
        turn_id=turn.id,
    )
    assert result.action is DirectorNextAction.REVIEW_EXECUTION_FAILURE
    assert turn.status == "awaiting_user"
    assert turn.wait_reason == "execution_failed"

    other_project, _other_user, _other_shot, _other_run, missing = await _seed(session)
    missing.node_run_ids = []
    await session.flush()
    with pytest.raises(ValidationAppError) as error:
        await DirectorNextActionService(session).reconcile(
            project=other_project,
            turn_id=missing.id,
        )
    assert error.value.details["code"] == "DIRECTOR_NODE_RUN_LINK_MISSING"


async def _proposal_turn(
    session: AsyncSession,
    *,
    statuses: list[str],
) -> tuple[Project, DirectorTurn, list[DirectorProposalItem]]:
    project, user, shot, _run, _unused = await _seed(session)
    thread = DirectorThread(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        title="Director",
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    proposal_status = (
        "pending"
        if "pending" in statuses
        else "applied"
        if "accepted" in statuses
        else "decided"
    )
    proposal = DirectorProposal(
        project_id=project.id,
        thread_id=thread.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        status=proposal_status,
        created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    items = [
        DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=project.id,
            command="shot.update_video_prompt",
            payload={"shot_id": str(shot.id), "video_prompt": f"proposal-{index}"},
            status=status,
        )
        for index, status in enumerate(statuses)
    ]
    session.add_all(items)
    await session.flush()
    turn = DirectorTurn(
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        request_key=f"proposal-turn:{uuid4().hex}",
        context_hash="d" * 64,
        request_summary={"max_steps": 4},
        status="awaiting_user",
        wait_reason="proposal_decision",
        proposal_id=proposal.id,
        step_count=1,
    )
    session.add(turn)
    await session.flush()
    return project, turn, items


@pytest.mark.asyncio
async def test_proposal_reconciliation_closes_rejection_and_reports_only_accepted_items(
    session: AsyncSession,
) -> None:
    project, rejected_turn, rejected_items = await _proposal_turn(
        session,
        statuses=["rejected", "rejected"],
    )
    rejected = await DirectorNextActionService(session).reconcile(
        project=project,
        turn_id=rejected_turn.id,
    )
    assert rejected.action is DirectorNextAction.PROPOSAL_REJECTED
    assert rejected.requires_confirmation is False
    assert rejected_turn.status == "completed"
    assert set(rejected.rejected_item_ids) == {item.id for item in rejected_items}
    revision = rejected_turn.revision
    replay = await DirectorNextActionService(session).reconcile(
        project=project,
        turn_id=rejected_turn.id,
    )
    assert replay.action is DirectorNextAction.PROPOSAL_REJECTED
    assert rejected_turn.revision == revision

    accepted_project, accepted_turn, accepted_items = await _proposal_turn(
        session,
        statuses=["accepted", "rejected"],
    )
    accepted = await DirectorNextActionService(session).reconcile(
        project=accepted_project,
        turn_id=accepted_turn.id,
    )
    assert accepted.action is DirectorNextAction.REVIEW_ACCEPTED_CHANGES
    assert accepted.accepted_item_ids == [accepted_items[0].id]
    assert accepted.rejected_item_ids == [accepted_items[1].id]


@pytest.mark.asyncio
async def test_event_key_reuse_with_changed_facts_conflicts(session: AsyncSession) -> None:
    project, _user, _shot, run, turn = await _seed(session)
    service = DirectorNextActionService(session)
    await service.reconcile(
        project=project,
        turn_id=turn.id,
        event_key="fixed-event",
    )
    run.status = "failed"
    await session.flush()
    with pytest.raises(ConflictError) as error:
        await service.reconcile(
            project=project,
            turn_id=turn.id,
            event_key="fixed-event",
        )
    assert error.value.details["code"] == "DIRECTOR_EVENT_KEY_REUSED"


@pytest.mark.asyncio
async def test_next_action_stops_at_step_limit_instead_of_looping(
    session: AsyncSession,
) -> None:
    project, _user, _shot, _run, turn = await _seed(session)
    turn.step_count = 4
    await session.flush()
    with pytest.raises(ConflictError) as error:
        await DirectorNextActionService(session).reconcile(
            project=project,
            turn_id=turn.id,
        )
    assert error.value.details["code"] == "DIRECTOR_TURN_LIMIT_REACHED"
    assert error.value.details["wait_reason"] == "step_limit_reached"
    assert turn.status == "failed"
    assert turn.wait_reason == "step_limit_reached"


@pytest.mark.asyncio
async def test_unchanged_checkpoint_still_enforces_expired_deadline(session: AsyncSession) -> None:
    project, _user, _shot, _run, turn = await _seed(session)
    service = DirectorNextActionService(session)
    await service.reconcile(project=project, turn_id=turn.id)
    turn.deadline = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(ConflictError) as error:
        await service.reconcile(project=project, turn_id=turn.id)
    assert error.value.details["wait_reason"] == "deadline_exceeded"
    assert turn.status == "failed"


@pytest.mark.asyncio
async def test_awaiting_user_limit_is_a_legal_terminal_transition(session: AsyncSession) -> None:
    project, turn, _items = await _proposal_turn(session, statuses=["pending"])
    turn.step_count = 4
    await session.flush()
    with pytest.raises(ConflictError) as error:
        await DirectorNextActionService(session).reconcile(project=project, turn_id=turn.id)
    assert error.value.details["code"] == "DIRECTOR_TURN_LIMIT_REACHED"
    assert turn.status == "failed"


@pytest.mark.asyncio
async def test_unknown_proposal_item_status_cannot_be_reported_as_rejected(
    session: AsyncSession,
) -> None:
    project, turn, _items = await _proposal_turn(session, statuses=["unexpected"])
    with pytest.raises(ValidationAppError) as error:
        await DirectorNextActionService(session).reconcile(project=project, turn_id=turn.id)
    assert error.value.details["code"] == "DIRECTOR_PROPOSAL_ITEM_STATE_INVALID"
    assert turn.status == "awaiting_user"


@pytest.mark.asyncio
async def test_scan_cursor_passes_unchanged_and_limit_failed_turns(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.shared.db import list_reconcilable_director_turn_rls_scopes
    from app.workers import jobs

    project, _user, _shot, _run, turn = await _seed(session)
    other_project, _u, _s, _r, other_turn = await _seed(session)
    turns = sorted([turn, other_turn], key=lambda row: row.id)
    first = await list_reconcilable_director_turn_rls_scopes(session, limit=1)
    assert first[0][0] == turns[0].id
    second = await list_reconcilable_director_turn_rls_scopes(
        session, limit=1, after_turn_id=first[0][0]
    )
    assert second[0][0] == turns[1].id
    # Exercise the real Worker with a one-row page and separate DB sessions.
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
    import app.shared.db as db
    original = db.list_reconcilable_director_turn_rls_scopes

    async def one_page(db_session: AsyncSession, *, limit: int, after_turn_id=None):
        return await original(db_session, limit=1, after_turn_id=after_turn_id)

    monkeypatch.setattr(db, "list_reconcilable_director_turn_rls_scopes", one_page)
    ctx = {"director_scan_state": {"cursor": None}}
    assert (await jobs.reconcile_waiting_director_turns(dict(ctx)))["reconciled"] == 1
    assert (await jobs.reconcile_waiting_director_turns(dict(ctx)))["reconciled"] == 1
    assert (await jobs.reconcile_waiting_director_turns(dict(ctx)))["reconciled"] == 0
    # A reached bound is committed by the Worker, not rolled back in its catch.
    turns[0].deadline = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert (await jobs.reconcile_waiting_director_turns(dict(ctx)))["failed"] == 1
    await session.refresh(turns[0])
    assert turns[0].status == "failed"
    assert turns[0].wait_reason == "deadline_exceeded"


@pytest.mark.asyncio
async def test_stale_proposal_is_not_misreported_as_user_rejection(session: AsyncSession) -> None:
    project, turn, items = await _proposal_turn(session, statuses=["accepted", "stale"])
    service = DirectorNextActionService(session)
    result = await service.reconcile(project=project, turn_id=turn.id)
    assert result.action is DirectorNextAction.REVIEW_STALE_PROPOSAL
    assert result.accepted_item_ids == [items[0].id]
    assert result.rejected_item_ids == []
    assert turn.status == "stale"
    assert await service.reconcile(project=project, turn_id=turn.id) == result


@pytest.mark.asyncio
async def test_final_allowed_checkpoint_replays_without_spending_another_step(
    session: AsyncSession,
) -> None:
    project, _user, _shot, run, turn = await _seed(session)
    turn.step_count = 3
    service = DirectorNextActionService(session)
    last = await service.reconcile(project=project, turn_id=turn.id)
    assert turn.step_count == 4
    assert await service.reconcile(project=project, turn_id=turn.id) == last
    assert turn.revision == last.turn_revision
    run.status = "failed"
    await session.flush()
    with pytest.raises(ConflictError) as error:
        await service.reconcile(project=project, turn_id=turn.id)
    assert error.value.details["wait_reason"] == "step_limit_reached"
    assert turn.status == "failed"


@pytest.mark.asyncio
async def test_detached_decision_endpoint_cannot_bypass_canonical_proposal_items(session):
    from app.director.turn_service import DirectorTurnService

    project, turn, items = await _proposal_turn(session, statuses=["pending"])
    turn.request_summary = {"task": "shot_director_recommendation"}
    with pytest.raises(ValidationAppError) as unsupported:
        await DirectorTurnService(session).record_user_decision(
            project_id=project.id, turn_id=turn.id, expected_revision=turn.revision,
            decision="reject", accepted_operation_indices=[],
        )
    assert unsupported.value.details["code"] == "DIRECTOR_DECISION_UNSUPPORTED"
    assert items[0].status == "pending"
    assert turn.status == "awaiting_user"


@pytest.mark.asyncio
async def test_formal_keyframe_checkpoint_offers_preview_only_and_is_versioned(session):
    project, _user, shot, run, turn = await _seed(session, autonomy="AUTO")
    artifact = Artifact(project_id=project.id, artifact_type="image", storage_state="available",
                        object_key=f"obj/{uuid4().hex}", content_hash="f" * 64,
                        mime_type="image/png", byte_size=1)
    session.add(artifact)
    await session.flush()
    run.status = "completed"
    run.result_artifact_id = artifact.id
    run.input_snapshot = {"shot_id": str(shot.id), "stage": "image_keyframe"}
    shot.formal_keyframe_artifact_id = artifact.id
    shot.version += 1
    await session.flush()
    service = DirectorNextActionService(session)
    result = await service.reconcile(project=project, turn_id=turn.id)
    assert result.action is DirectorNextAction.PREVIEW_NEXT_STAGE
    assert result.requires_confirmation and result.shot_version == shot.version
    assert turn.status == "completed"
    assert await service.reconcile(project=project, turn_id=turn.id) == result
    assert len((await session.execute(select(NodeRun))).scalars().all()) == 1
    assert (await session.execute(select(ProviderOperation))).scalars().all() == []


@pytest.mark.asyncio
async def test_cross_shot_node_run_link_is_rejected_even_inside_one_project(session):
    project, _user, shot, _run, turn = await _seed(session)
    other = Shot(project_id=project.id, scene_id=shot.scene_id, shot_number=2, version=1,
                 visual_description="Other Shot")
    session.add(other)
    await session.flush()
    turn.scope_entity_id = other.id
    await session.flush()
    with pytest.raises(ValidationAppError) as invalid:
        await DirectorNextActionService(session).reconcile(project=project, turn_id=turn.id)
    assert invalid.value.details["code"] == "DIRECTOR_NODE_RUN_LINK_MISSING"
    assert turn.step_count == 1


@pytest.mark.asyncio
async def test_expired_director_does_not_roll_back_valid_formal_selection(session):
    from app.director.business_checkpoints import DirectorBusinessCheckpoints
    from app.production.formal_selection import set_formal_keyframe

    project, _user, shot, run, turn = await _seed(session, autonomy="AUTO")
    artifact = Artifact(project_id=project.id, artifact_type="image", storage_state="available",
                        object_key=f"obj/{uuid4().hex}", content_hash="e" * 64,
                        mime_type="image/png", byte_size=1, produced_by_run_id=run.id)
    session.add(artifact)
    await session.flush()
    run.status = "completed"
    run.result_artifact_id = artifact.id
    run.input_snapshot = {"shot_id": str(shot.id), "stage": "image_keyframe"}
    turn.deadline = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    await set_formal_keyframe(session, project_id=project.id, shot_id=shot.id,
                              artifact_id=artifact.id, expected_shot_version=shot.version)
    await DirectorBusinessCheckpoints(session).reconcile_business_fact(
        project=project, shot_id=shot.id,
    )
    await session.commit()
    await session.refresh(shot)
    assert shot.formal_keyframe_artifact_id == artifact.id
    assert shot.version == 2
    assert turn.status == "failed" and turn.wait_reason == "deadline_exceeded"
