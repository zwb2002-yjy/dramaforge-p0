"""MasterRun origin binding, immutable plans and control receipts (T06)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.contracts.domain_events import MasterRunPlanApplied, MasterRunPlanProposed
from app.director.assistant_models import DirectorThread
from app.director.master_run_models import (
    DirectorMasterRun,
    DirectorMasterRunControlReceipt,
    DirectorMasterRunPlan,
)
from app.director.master_runs import MasterRunService, plan_hash
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(session: AsyncSession) -> tuple[Project, User, DirectorThread]:
    user = User(
        email=f"master-run-{uuid4().hex}@example.com", display_name="Owner", password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        work_type="serial_comic",
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    thread = DirectorThread(
        project_id=project.id, scope_type="project", scope_entity_id=project.id,
        title="机构创作", created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    session.info["selected_workspace_id"] = workspace.id
    return project, user, thread


async def _turn(
    session: AsyncSession, project: Project, user: User, thread: DirectorThread,
    *, kind: str = "agent", thread_id=None,
) -> DirectorTurn:
    turn = DirectorTurn(
        workspace_id=project.workspace_id,
        project_id=project.id,
        actor_id=user.id,
        thread_id=thread.id if thread_id is None else thread_id,
        turn_kind=kind,
        scope_type="project",
        scope_entity_id=project.id,
        request_key=f"turn-{uuid4().hex}",
        context_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        status="thinking",
    )
    session.add(turn)
    await session.flush()
    return turn


async def _plan_proposal(
    session: AsyncSession, project: Project, user: User, thread: DirectorThread,
):
    proposal = DirectorProposal(
        project_id=project.id, thread_id=thread.id, scope_type="project",
        scope_entity_id=project.id, created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    return proposal


def _plan(run: DirectorMasterRun, **overrides) -> dict[str, object]:
    current_plan = overrides.pop("current_plan", None)
    data: dict[str, object] = {
        "goal": run.goal,
        "flows": [],
        "dependencies": [],
        "completion": [{"rule_id": "all_required_steps_succeeded"}],
        "input_versions": {"research": 1},
        "limits": {"max_model_calls": 4, "max_steps": 6},
        "decision_basis": {
            "expected_run_revision": run.revision,
            "expected_control_epoch": run.control_epoch,
            "current_plan_id": str(run.current_plan_id) if run.current_plan_id else None,
            "current_plan_revision": current_plan.revision if current_plan else None,
        },
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("completion", [
    [],
    [{"rule_id": "project_delivery_ready_v1", "work_type": "serial_comic", "targets": []}],
    [{"rule_id": "episode_export_ready_v1", "target": {"episode_id": None}}],
    [{"rule_id": "episode_export_ready_v1", "target": {"episode_id": str(uuid4()),
                                                       "timeline_version": 1}}],
    [{"rule_id": "all_required_steps_succeeded", "satisfied": True}],
    [{"rule_id": "project_delivery_ready_v1", "work_type": "single_comic",
      "targets": [{"episode_id": str(uuid4()), "predicate_results": []}]}],
])
def test_plan_completion_accepts_only_declared_targets(completion):
    basis = {"expected_run_revision": 1, "expected_control_epoch": 0,
             "current_plan_id": None, "current_plan_revision": None}
    with pytest.raises(ValidationAppError) as refused:
        MasterRunService.validate_plan_data({
            "goal":"Film", "flows":[], "dependencies":[], "completion":completion,
            "input_versions":{}, "limits":{}, "decision_basis":basis,
        })
    assert refused.value.details["code"] == "MASTER_RUN_COMPLETION_SHAPE"


async def test_only_a_thread_bound_agent_turn_can_originate_one_goal(session: AsyncSession):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    workflow_turn = await _turn(session, project, user, thread, kind="workflow")
    with pytest.raises(ValidationAppError) as refused:
        await service.create_for_origin_turn(turn_id=workflow_turn.id, goal="研究古城")
    assert refused.value.details["code"] == "MASTER_RUN_ORIGIN_KIND"
    threadless = await _turn(session, project, user, thread, thread_id=None)
    threadless.thread_id = None
    await session.flush()
    with pytest.raises(ValidationAppError):
        await service.create_for_origin_turn(turn_id=threadless.id, goal="研究古城")
    assert await session.scalar(select(func.count(DirectorMasterRun.id))) == 0

    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="  整理古城灯会资料  ")
    assert run.goal == "整理古城灯会资料"
    assert run.status == "planning" and run.revision == 1 and run.control_epoch == 0
    assert run.source_thread_id == thread.id and run.origin_turn_id == turn.id
    assert run.origin_turn_kind == "agent"
    assert (await session.get(DirectorTurn, turn.id)).master_run_id == run.id
    # Replaying the same origin returns the binding; a different goal cannot rebind.
    assert (await service.create_for_origin_turn(
        turn_id=turn.id, goal="整理古城灯会资料"
    )).id == run.id
    with pytest.raises(ConflictError) as rebound:
        await service.create_for_origin_turn(turn_id=turn.id, goal="另一个目标")
    assert rebound.value.details["code"] == "MASTER_RUN_ORIGIN_REBOUND"
    # Ordinary conversation (a turn without create_goal) never creates a run.
    await _turn(session, project, user, thread)
    assert await session.scalar(select(func.count(DirectorMasterRun.id))) == 1


async def test_plan_candidates_are_immutable_hash_deduplicated_and_do_not_advance_the_run(
    session: AsyncSession,
):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="拍一支灯会宣传片")
    proposal = await _plan_proposal(session, project, user, thread)
    basis = _plan(run)
    plan = await service.append_plan(
        run_id=run.id, proposal_id=proposal.id, plan_data=basis, created_by_turn_id=turn.id,
    )
    assert plan.revision == 1
    assert plan.plan_hash == plan_hash(plan.schema_version, basis)
    assert len(plan.plan_hash) == 64
    # A candidate plan never advances the accepted business state.
    refreshed = await session.get(DirectorMasterRun, run.id)
    await session.refresh(refreshed)
    assert refreshed.revision == 1 and refreshed.current_plan_id is None
    assert refreshed.status == "planning"
    assert (await session.get(DirectorTurn, turn.id)).plan_revision == 1
    # The same content returns the original row instead of a second revision.
    assert (await service.append_plan(
        run_id=run.id, proposal_id=proposal.id, plan_data=basis,
    )).id == plan.id
    # A stale basis (a different revision isn't observed state) is refused.
    stale = _plan(refreshed)
    stale["decision_basis"]["expected_run_revision"] = 99
    with pytest.raises(ConflictError) as refused:
        await service.append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=stale)
    assert refused.value.details["code"] == "MASTER_RUN_PLAN_STALE"
    # Unknown top-level fields are rejected instead of silently stored.
    broken = _plan(refreshed)
    broken["freeform_sql"] = "select 1"
    with pytest.raises(ValidationAppError):
        await service.append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=broken)
    # The decision reference must be this project's typed plan item.
    other_proposal = await _plan_proposal(session, project, user, thread)
    session.add(DirectorProposalItem(
        proposal_id=other_proposal.id, project_id=project.id,
        command="story.upsert_episode", status="pending", payload={},
    ))
    await session.flush()
    with pytest.raises(ValidationAppError):
        await service.append_plan(
            run_id=run.id, proposal_id=other_proposal.id, plan_data=_plan(refreshed),
        )
    events = list(await session.scalars(select(EventLog)))
    assert any(
        event.event_type == "master_run_plan_proposed"
        and isinstance(event.payload, dict)
        and event.payload["notice"]["kind"] == MasterRunPlanProposed.model_fields["kind"].default
        for event in events
    )


async def test_plan_apply_advances_pointer_epoch_and_revision_with_cas(session: AsyncSession):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="拍一支灯会宣传片")
    proposal = await _plan_proposal(session, project, user, thread)
    plan = await service.append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=_plan(run))
    await session.refresh(run)
    assert await service.apply_plan(
        decision_ref=plan.decision_ref, expected_plan_hash=plan.plan_hash,
        run_id=run.id, plan_id=plan.id, expected_revision=1, expected_control_epoch=0,
    )
    await session.refresh(run)
    assert run.current_plan_id == plan.id
    assert run.revision == 2 and run.control_epoch == 1
    assert run.status == "waiting" and run.wait_reason == "production_pending"
    applied = [
        event for event in await session.scalars(select(EventLog))
        if event.payload.get("notice", {}).get("kind") == "master_run_plan_applied"
    ]
    assert applied and applied[0].payload["notice"]["applied_run_revision"] == 2
    assert MasterRunPlanApplied.model_fields["kind"].default == "master_run_plan_applied"
    with pytest.raises(ConflictError) as stale_epoch:
        await service.apply_plan(
            decision_ref=plan.decision_ref, expected_plan_hash=plan.plan_hash,
            run_id=run.id, plan_id=plan.id, expected_revision=2, expected_control_epoch=0,
        )
    assert stale_epoch.value.details["code"] == "MASTER_RUN_EPOCH_CONFLICT"
    # A later accepted plan may replace the pointer, but never move it backwards.
    # Each candidate plan owns exactly one typed decision item (UNIQUE decision_ref).
    second_proposal = await _plan_proposal(session, project, user, thread)
    second = await service.append_plan(
        run_id=run.id, proposal_id=second_proposal.id, plan_data=_plan(run, current_plan=plan),
    )
    assert second.revision == 2
    await service.apply_plan(
        decision_ref=second.decision_ref, expected_plan_hash=second.plan_hash,
        run_id=run.id, plan_id=second.id, expected_revision=2, expected_control_epoch=1,
    )
    await session.refresh(run)
    with pytest.raises(ConflictError) as backwards:
        await service.apply_plan(
            decision_ref=plan.decision_ref, expected_plan_hash=plan.plan_hash,
            run_id=run.id, plan_id=plan.id,
            expected_revision=run.revision, expected_control_epoch=run.control_epoch,
        )
    assert backwards.value.details["code"] == "MASTER_RUN_PLAN_SUPERSEDED"


async def test_confirmation_rechecks_content_when_both_hash_fields_agree(session: AsyncSession):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="核对保存的候选")
    proposal = await _plan_proposal(session, project, user, thread)
    plan = await service.append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=_plan(run))
    # Simulate an inconsistent saved snapshot in the isolated SQLite fixture.
    plan.plan_data = {**plan.plan_data, "limits": {"max_steps": 99}}
    await session.flush()
    with pytest.raises(ConflictError) as refused:
        await service.apply_plan(
            run_id=run.id, plan_id=plan.id, decision_ref=plan.decision_ref,
            expected_plan_hash=plan.plan_hash, expected_revision=1, expected_control_epoch=0,
        )
    assert refused.value.details["code"] == "MASTER_RUN_PLAN_DECISION"
    assert (run.current_plan_id, run.revision, run.control_epoch) == (None, 1, 0)


async def test_control_receipts_are_idempotent_and_state_machine_stays_closed(
    session: AsyncSession,
):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="整理古城资料")

    paused = await service.control(run_id=run.id, operation="pause", expected_revision=1)
    assert paused["status"] == "paused" and paused["desired_state"] == "pause"
    assert paused["result_revision"] == 2 and paused["control_epoch"] == 1
    await session.refresh(run)
    assert run.revision == 2
    # Same operation+revision replays the stored receipt; a different payload 409s.
    assert await service.control(
        run_id=run.id, operation="pause", expected_revision=1,
    ) == paused
    with pytest.raises(ConflictError) as changed:
        await service.control(
            run_id=run.id, operation="pause", expected_revision=1, reason="different",
        )
    assert changed.value.details["code"] == "MASTER_RUN_RECEIPT_CONFLICT"
    # A stale revision cannot mint a second receipt for the same operation.
    with pytest.raises(ConflictError) as stale:
        await service.control(run_id=run.id, operation="pause", expected_revision=2)
    assert stale.value.details["code"] == "MASTER_RUN_STATE_CONFLICT"
    assert await session.scalar(
        select(func.count(DirectorMasterRunControlReceipt.id))
    ) == 1

    resumed = await service.control(run_id=run.id, operation="resume", expected_revision=2)
    assert resumed["status"] == "planning" and resumed["desired_state"] == "run"
    with pytest.raises(ConflictError) as invalid:
        await service.control(run_id=run.id, operation="resume", expected_revision=3)
    assert invalid.value.details["code"] == "MASTER_RUN_STATE_CONFLICT"

    cancelled = await service.control(
        run_id=run.id, operation="cancel", expected_revision=3, reason="用户结束",
    )
    assert cancelled["status"] == "cancelled" and cancelled["desired_state"] == "cancel"
    await session.refresh(run)
    assert run.finished_at is not None
    terminal_revision = run.revision
    for operation in ("pause", "resume", "verify"):
        with pytest.raises(ConflictError):
            await service.control(
                run_id=run.id, operation=operation, expected_revision=terminal_revision,
            )
    with pytest.raises(ConflictError) as archived_too_early:
        await service.archive(
            run_id=run.id, expected_revision=terminal_revision - 1, archived=True,
        )
    assert archived_too_early.value.details["code"] == "MASTER_RUN_VERSION_CONFLICT"
    archived = await service.archive(
        run_id=run.id, expected_revision=terminal_revision, archived=True,
    )
    assert archived.archived_at is not None and archived.revision == terminal_revision + 1
    restored = await service.archive(
        run_id=run.id, expected_revision=archived.revision, archived=False,
    )
    assert restored.archived_at is None


async def test_verify_records_evidence_without_declaring_success(session: AsyncSession):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="整理古城资料")
    with pytest.raises(ConflictError) as not_waiting:
        await service.control(run_id=run.id, operation="verify", expected_revision=1)
    assert not_waiting.value.details["code"] == "MASTER_RUN_STATE_CONFLICT"
    proposal = await _plan_proposal(session, project, user, thread)
    plan = await service.append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=_plan(run))
    await session.refresh(run)
    await service.apply_plan(
        decision_ref=plan.decision_ref, expected_plan_hash=plan.plan_hash,
        run_id=run.id, plan_id=plan.id, expected_revision=run.revision,
        expected_control_epoch=run.control_epoch,
    )
    await session.refresh(run)
    receipt = await service.control(
        run_id=run.id, operation="verify", expected_revision=run.revision,
    )
    verification = receipt["verification"]
    assert verification["satisfied"] is False
    assert {check["rule_id"] for check in verification["checks"]} == {
        "all_required_steps_succeeded",
        "no_unresolved_external",
        "business_flow_completed_v1",
    }
    assert receipt["unresolved_external_count"] == 0
    await session.refresh(run)
    # An unmet predicate keeps the goal waiting; it never becomes success.
    assert run.status == "waiting" and run.finished_at is None
    assert run.revision == receipt["result_revision"]


async def test_unknown_run_and_plan_are_project_scoped(session: AsyncSession):
    project, user, thread = await _seed(session)
    service = MasterRunService(session, actor=user, project=project)
    with pytest.raises(NotFoundError):
        await service.get(uuid4())
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="整理古城资料")
    with pytest.raises(NotFoundError):
        await service.get_plan(run.id, uuid4())
    assert await session.scalar(select(func.count(DirectorMasterRunPlan.id))) == 0
