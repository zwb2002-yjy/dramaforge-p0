"""Only the owner's selected item may activate its original, still-current plan."""

import asyncio

import pytest
from app.access.models import Project, User, Workspace
from app.director.assistant_models import DirectorThread
from app.director.business_flow_models import DirectorBusinessFlowInstance, DirectorBusinessFlowStep
from app.director.master_run_models import DirectorMasterRun
from app.director.master_runs import PLAN_COMMAND, MasterRunService
from app.director.proposal_commands import ProposalCommandError, ProposalCommandRegistry
from app.director.proposal_models import DirectorProposalItem
from app.shared.db import set_rls_context
from sqlalchemy import func, select, text
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_master_runs import _plan, _plan_proposal, _turn


@pytest.mark.parametrize(
    "case",
    [
        "concurrent",
        "item",
        "hash",
        "old_payload",
        "basis",
        "partial_flow",
        "rejected",
    ],
)
async def test_confirm_frozen_master_plan_via_authenticated_apply(http_agent, case):
    agent = http_agent
    async with agent.factory() as db:
        assert await db.scalar(text("SELECT current_user")) == "dramaforge_app"
        # The owner is authenticated by the HTTP fixture. Use its identity to
        # build the candidate through the product service in that same scope.
        from sqlalchemy.orm import Session

        with Session(agent.database.engine) as seed:
            owner_id = seed.get(Workspace, agent.workspace_id).owner_user_id
        await set_rls_context(
            db,
            user_id=owner_id,
            workspace_id=agent.workspace_id,
            project_id=agent.project_id,
        )
        owner = await db.get(User, owner_id)
        project = await db.get(Project, agent.project_id)
        thread = DirectorThread(
            project_id=project.id,
            scope_type="project",
            scope_entity_id=project.id,
            title="Plan",
            created_by=owner.id,
        )
        db.add(thread)
        await db.flush()
        turn = await _turn(db, project, owner, thread)
        service = MasterRunService(db, project=project, actor=owner)
        run = await service.create_for_origin_turn(turn_id=turn.id, goal="Fixture asset audit")
        proposal = await _plan_proposal(db, project, owner, thread)
        turn.proposal_id = proposal.id
        flow = {
            "flow_key": "audit",
            "definition_key": "project_asset_audit",
            "definition_version": "1",
            "scope_type": "project",
            "scope_entity_id": str(project.id),
            "input": {},
        }
        flows = [flow]
        if case == "partial_flow":
            flows.append({**flow, "flow_key": "second", "scope_type": "scene"})
        plan = await service.append_plan(
            run_id=run.id,
            proposal_id=proposal.id,
            plan_data=_plan(run, flows=flows),
            created_by_turn_id=turn.id,
        )
        item = await db.get(DirectorProposalItem, plan.decision_ref)
        assert item.payload["plan_hash"] == plan.plan_hash and item.status == "pending"
        # Internal command delivery carries no human selection, even with valid parameters.
        with pytest.raises(ProposalCommandError) as unconfirmed:
            await ProposalCommandRegistry(db, actor_id=owner.id).apply(
                project_id=project.id,
                command=PLAN_COMMAND,
                payload=item.payload,
                command_key=f"proposal-item-{item.id}",
            )
        assert unconfirmed.value.details["code"] == "MASTER_RUN_PLAN_DECISION"
        selected = item
        if case == "item":
            selected = DirectorProposalItem(
                project_id=project.id,
                proposal_id=item.proposal_id,
                command=PLAN_COMMAND,
                payload=dict(item.payload),
            )
            db.add(selected)
        elif case == "hash":
            item.payload = {**item.payload, "plan_hash": "0" * 64}
        elif case == "old_payload":
            item.payload = {k: v for k, v in item.payload.items() if k != "plan_hash"}
        elif case == "basis":
            await service.control(run_id=run.id, operation="pause", expected_revision=run.revision)
            await service.control(run_id=run.id, operation="resume", expected_revision=run.revision)
            item.payload = {
                **item.payload,
                "expected_run_revision": run.revision,
                "expected_control_epoch": run.control_epoch,
            }
        await db.flush()
        original = (run.current_plan_id, run.revision, run.control_epoch, run.status)
        run_id, plan_id, item_id = run.id, plan.id, selected.id
        path = f"/api/v1/projects/{project.id}/director/proposals/{item.proposal_id}/apply"
        await db.commit()

    async def post(decision):
        response = await agent.client.post(
            path,
            headers=agent.headers,
            json={
                "decisions": [{"item_id": str(item_id), "decision": decision}],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    if case == "concurrent":
        first, again = await asyncio.gather(post("accepted"), post("accepted"))
        assert first == again == await post("accepted")
        assert first["accepted"] == [str(item_id)] and not first["failed"]
    elif case == "rejected":
        assert (await post("rejected"))["rejected"] == [str(item_id)]
        assert (await post("accepted"))["failed"]
    else:
        refused = await post("accepted")
        assert not refused["accepted"] and len(refused["failed"]) == 1
        assert (
            refused["failed"][0]["code"]
            == {
                "item": "MASTER_RUN_PLAN_DECISION",
                "hash": "MASTER_RUN_PLAN_DECISION",
                "old_payload": "MASTER_RUN_PLAN_APPLY_INPUT",
                "basis": "MASTER_RUN_PLAN_STALE",
                "partial_flow": "BUSINESS_FLOW_SCOPE",
            }[case]
        )
    async with agent.factory() as db:
        await set_rls_context(
            db,
            user_id=owner_id,
            workspace_id=agent.workspace_id,
            project_id=agent.project_id,
        )
        run = await db.get(DirectorMasterRun, run_id)
        persisted = await db.get(DirectorProposalItem, item_id)
        flows_count = await db.scalar(
            select(func.count())
            .select_from(DirectorBusinessFlowInstance)
            .where(DirectorBusinessFlowInstance.supervisor_run_id == run_id)
        )
        steps_count = await db.scalar(
            select(func.count())
            .select_from(DirectorBusinessFlowStep)
            .where(DirectorBusinessFlowStep.supervisor_run_id == run_id)
        )
        if case == "concurrent":
            assert (run.current_plan_id, run.revision, run.control_epoch) == (plan_id, 2, 1)
            assert persisted.status == "accepted" and (flows_count, steps_count) == (1, 2)
        else:
            assert (run.current_plan_id, run.revision, run.control_epoch, run.status) == original
            assert persisted.status == ("rejected" if case == "rejected" else "pending")
            assert (flows_count, steps_count) == (0, 0)
    assert not agent.chat.requests
