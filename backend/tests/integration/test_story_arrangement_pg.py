"""Exercise Story's partial Apply endpoint with two independently confirmed goals."""

import asyncio
from uuid import UUID

from app.access.models import Project, User, Workspace
from app.assets.models import Episode
from app.director.assistant_models import DirectorThread
from app.director.business_flow_models import DirectorBusinessFlowStepAttempt
from app.director.master_runs import MasterRunService
from app.shared.db import set_rls_context
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_master_runs import _turn


async def test_only_new_accepted_episodes_enter_the_selected_plan(http_agent):
    agent = http_agent
    project_path = f"/api/v1/projects/{agent.project_id}"
    goals = project_path + "/director/master-runs"
    with Session(agent.database.engine) as setup:
        project = setup.get(Project, agent.project_id)
        project.work_type, project.planned_episode_count = "serial_comic", 2
        owner_id = setup.get(Workspace, agent.workspace_id).owner_user_id
        setup.commit()

    created = await agent.client.post(
        agent.threads_path,
        headers=agent.headers,
        json={
            "scope_type": "project",
            "scope_entity_id": str(agent.project_id),
        },
    )
    assert created.status_code in (200, 201)
    thread_id = UUID(created.json()["id"])

    async def goal():
        async with agent.factory() as db:
            await set_rls_context(
                db, user_id=owner_id, workspace_id=agent.workspace_id, project_id=agent.project_id
            )
            project, owner = await db.get(Project, agent.project_id), await db.get(User, owner_id)
            thread = await db.get(DirectorThread, thread_id)
            turn = await _turn(db, project, owner, thread)
            service = MasterRunService(db, project=project, actor=owner)
            run = await service.create_for_origin_turn(turn_id=turn.id, goal="按正式分集核验交付")
            plan, proposal = await service.propose_delivery_check(turn, story_arrangement=True)
            turn.proposal_id = proposal
            await db.commit()
        res = await agent.client.post(
            f"{project_path}/director/proposals/{proposal}/apply",
            headers=agent.headers,
            json={"decisions": [{"item_id": str(plan.decision_ref), "decision": "accepted"}]},
        )
        assert res.json()["accepted"] == [str(plan.decision_ref)], res.text
        return {"master_run_id": str(run.id), "plan_id": str(plan.id), "control_epoch": 1}

    main, other = await goal(), await goal()
    story = project_path + "/story/proposals"

    async def candidate(key):
        draft = "\n".join(
            f"# 第 {n} 集 — 灯会{key}{n}\n## 场景 1 — 桥边 / 夜间\n"
            f"### 镜头 1 — 中景\n画面：灯笼照亮河面。"
            for n in (1, 2)
        )
        res = await agent.client.post(
            story,
            headers=agent.headers,
            json={
                "idempotency_key": key,
                "draft_text": draft,
                "filename": "arrangement.md",
            },
        )
        assert res.status_code == 201, res.text
        rows = res.json()["operations"]
        return res.json()["id"], {
            i["payload"]["episode_number"]: i["id"]
            for i in rows
            if i["command"] == "story.upsert_episode"
        }

    async def decide(proposal, decisions, plan=main):
        return await agent.client.post(
            f"{story}/{proposal}/apply",
            headers=agent.headers,
            json={
                "decisions": [{"item_id": item, "decision": choice} for item, choice in decisions],
                **({"arrangement_plan": plan} if plan else {}),
            },
        )

    async def check(plan):
        path = goals + "/" + plan["master_run_id"]
        rev = (await agent.client.get(path)).json()["revision"]
        result = await agent.client.post(
            path + "/verify", headers=agent.headers, json={"expected_revision": rev}
        )
        assert result.status_code == 200, result.text
        return result.json()["verification"]["checks"][-1]

    proposal, items = await candidate("first")
    assert (await check(main))["missing_episode_ranges"] == [[1, 2]]
    decisions = [(items[1], "accepted"), (items[2], "rejected")]
    a, b = await asyncio.gather(decide(proposal, decisions), decide(proposal, decisions))
    assert a.json() == b.json() == {"accepted": [items[1]], "rejected": [items[2]], "failed": []}
    assert (await decide(proposal, [(items[1], "accepted")], other)).status_code == 409
    first_check = await check(main)
    assert first_check["missing_episode_ranges"] == [[2, 2]]
    assert [r["item_id"] for r in first_check["story_receipts"]] == [items[1]]
    assert (await check(other))["missing_episode_ranges"] == [[1, 2]]
    fresh, new_items = await candidate("second")
    assert (await decide(fresh, [(new_items[2], "accepted")], None)).json()["accepted"] == [
        new_items[2]
    ]
    assert (await decide(fresh, [(new_items[2], "accepted")])).status_code == 409
    assert (await check(main))["missing_episode_ranges"] == [[2, 2]]
    fresh, new_items = await candidate("third")
    assert (
        await decide(fresh, [(new_items[2], "accepted")], {**main, "control_epoch": 0})
    ).status_code == 409
    assert (await decide(fresh, [(new_items[2], "accepted")])).json()["accepted"] == [new_items[2]]
    final = await check(main)
    assert not final["satisfied"]  # Both formal episodes now exist, but neither has a film.
    assert not final["missing_episode_ranges"] and len(final["evidence_refs"]) == 2
    assert all(p["blockers"] == ["DELIVERY_SESSION_MISSING"] for p in final["evidence_refs"])
    assert {r["item_id"] for r in final["story_receipts"]} == {items[1], new_items[2]}
    with Session(agent.database.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DirectorBusinessFlowStepAttempt)
                .where(
                    DirectorBusinessFlowStepAttempt.supervisor_run_id == UUID(main["master_run_id"])
                )
            )
            == 2
        )
        ep = db.get(Episode, UUID(final["story_receipts"][0]["episode_id"]))
        assert ep.version == final["story_receipts"][0]["episode_version"]
    changed, changed_items = await candidate("new-version")
    closed = (await decide(changed, [(changed_items[1], "accepted")])).json()
    assert not closed["accepted"] and closed["failed"][0]["code"] == "STORY_ARRANGEMENT_CLOSED"
    assert (await check(main))["story_receipts"] == final["story_receipts"]
    assert (await decide(changed, [(changed_items[1], "accepted")], None)).json()["accepted"] == [
        changed_items[1]
    ]
    assert (await check(main))["reason_code"] == "STORY_EPISODE_CHANGED"
    # Completing a partial arrangement must recheck earlier approvals.
    one, selected = await candidate("other-one")
    assert (await decide(one, [(selected[1], "accepted")], other)).json()["accepted"] == [
        selected[1]
    ]
    ordinary, selected = await candidate("ordinary-edit")
    assert (await decide(ordinary, [(selected[1], "accepted")], None)).json()["accepted"]
    two, selected = await candidate("other-two")
    assert (await decide(two, [(selected[2], "accepted")], other)).json()["accepted"]
    assert (await check(other))["missing_episode_ranges"] == [[1, 1]]
    updated, selected = await candidate("other-reconfirm")
    assert (await decide(updated, [(selected[1], "accepted")], other)).json()["accepted"]
    assert not (await check(other))["missing_episode_ranges"]
    assert not agent.chat.requests
