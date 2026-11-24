"""Project-scoped flow pages expose business identities and counts, not private tool output."""

from uuid import UUID, uuid4

from app.access.models import Project, User, Workspace
from app.director.assistant_models import DirectorThread
from app.director.business_flows import BusinessFlowService
from app.director.master_runs import MasterRunService
from app.shared.db import set_rls_context
from sqlalchemy.orm import Session
from test_business_flows_pg import REGISTRY, _flow_spec, _plan
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_master_runs import _plan_proposal, _turn


async def test_paged_steps_hide_raw_receipts_and_inaccessible_result_refs(http_agent):
    a = http_agent
    with Session(a.database.engine) as admin:
        owner = admin.get(Workspace, a.workspace_id).owner_user_id
    created = await a.client.post(a.threads_path, json={"scope_type": "project"}, headers=a.headers)
    assert created.status_code == 201, created.text
    inaccessible = str(uuid4())
    async with a.factory() as db:
        await set_rls_context(
            db, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        db.info["selected_workspace_id"] = a.workspace_id
        actor, project = await db.get(User, owner), await db.get(Project, a.project_id)
        thread = await db.get(DirectorThread, UUID(created.json()["id"]))
        turn = await _turn(db, project, actor, thread)
        proposal = await _plan_proposal(db, project, actor, thread)
        supervisor = MasterRunService(db, actor=actor, project=project, flow_registry=REGISTRY)
        run = await supervisor.create_for_origin_turn(turn_id=turn.id, goal="核对现有内容")
        plan = await supervisor.append_plan(
            run_id=run.id,
            proposal_id=proposal.id,
            plan_data=_plan(run, flows=[_flow_spec(project.id)]),
        )
        await db.refresh(run)
        await supervisor.apply_plan(
            decision_ref=plan.decision_ref,
            expected_plan_hash=plan.plan_hash,
            run_id=run.id,
            plan_id=plan.id,
            expected_revision=run.revision,
            expected_control_epoch=run.control_epoch,
        )
        flows = BusinessFlowService(db, actor=actor, project=project, registry=REGISTRY)
        flow = (await flows.list_for_run(run.id))[0]

        class Result:
            async def execute(self, **kwargs):
                return {
                    "ok": True,
                    "proposal_ids": [str(proposal.id), inaccessible],
                    "internal_fixture": "hidden-tool-output",
                }

        await flows.advance(flow, executor=Result())
        await db.commit()
    base = f"/api/v1/projects/{a.project_id}/director"
    listed = await a.client.get(f"{base}/master-runs/{run.id}/business-flows?limit=1")
    assert listed.status_code == 200 and listed.json()["total"] == 1, listed.text
    steps = f"{base}/business-flows/{flow.id}/steps"
    pages = [(await a.client.get(steps, params={"limit": 1, "offset": i})).json() for i in (0, 1)]
    assert [page["total"] for page in pages] == [2, 2]
    assert [page["next_offset"] for page in pages] == [1, None]
    step = next(p["items"][0] for p in pages if p["items"][0]["step_key"] == "read")
    refs = [
        {
            "kind": "proposal",
            "id": str(proposal.id),
            "display_name": f"导演提案 · {str(proposal.id)[:8]}",
        }
    ]
    assert step["result_refs"] == step["completion"]["evidence_refs"] == refs
    path = f"{steps}/{step['id']}/attempts"
    view = await a.client.get(path)
    assert view.status_code == 200 and view.json()["total"] == 1, view.text
    attempt = view.json()["items"][0]
    assert attempt["receipt"] is None and attempt["result_refs"] == refs
    assert "hidden-tool-output" not in view.text and inaccessible not in view.text
    assert (
        await a.client.get(path, headers={"X-Workspace-Id": str(a.other_workspace_id)})
    ).status_code == 404
    assert not a.chat.requests
