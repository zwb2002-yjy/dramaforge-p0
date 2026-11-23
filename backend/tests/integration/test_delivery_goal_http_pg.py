"""An explicit goal Turn proposes, owner applies, and only real receipts can verify it."""

import json

import httpx
from app.access.models import Project
from app.assets.models import Episode
from sqlalchemy.orm import Session
from test_director_agent_http_pg import _accept, _execute
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_delivery_goal_via_project_conversation(http_agent, monkeypatch):
    agent = http_agent
    with Session(agent.database.engine) as db:
        project = db.get(Project, agent.project_id)
        project.work_type, project.planned_episode_count = "serial_comic", 2
        db.add(Episode(project_id=project.id, episode_number=2))
        db.commit()
    calls = []

    async def plan_model(request):
        body = json.loads(request.content)
        assert "project_delivery_plan_propose" in {t["function"]["name"] for t in body["tools"]}
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "plan",
                                    "type": "function",
                                    "function": {
                                        "name": "project_delivery_plan_propose",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
        )

    monkeypatch.setattr(agent.chat, "handle", plan_model)
    thread = await agent.client.post(
        agent.threads_path,
        headers=agent.headers,
        json={
            "scope_type": "project",
            "scope_entity_id": str(agent.project_id),
        },
    )
    tid = thread.json()["id"]
    accepted = await _accept(
        agent,
        tid,
        {"intent": "create_goal", "content": "核对两集成片交付", "request_key": "delivery"},
    )
    result = await _execute(agent, accepted["turn_id"])
    assert result["status"] == "completed", result
    root = f"/api/v1/projects/{agent.project_id}/director/master-runs"
    listed = await agent.client.get(root)
    assert listed.status_code == 200, listed.text
    goal = listed.json()["items"][0]
    assert goal["status"] == "planning" and goal["current_plan_id"] is None
    path = root + "/" + goal["id"]
    plans = (await agent.client.get(path + "/plans")).json()
    assert len(plans) == 1
    plan = plans[0]
    assert plan["proposal_id"] and plan["decision_ref"]
    assert plan["decision_status"] == "pending"
    assert len(plan["plan_data"]["completion"][0]["targets"]) == 2
    apply = await agent.client.post(
        f"/api/v1/projects/{agent.project_id}/director/proposals/{plan['proposal_id']}/apply",
        headers=agent.headers,
        json={"decisions": [{"item_id": plan["decision_ref"], "decision": "accepted"}]},
    )
    assert apply.json()["accepted"] == [plan["decision_ref"]], apply.text
    current = (await agent.client.get(path)).json()
    assert current["current_plan_id"] == plan["id"] and "verify" in current["available_actions"]
    body = {"expected_revision": current["revision"]}
    assert (await agent.client.post(path + "/verify", json=body)).status_code == 403
    forged = await agent.client.post(
        path + "/verify", headers=agent.headers, json={**body, "satisfied": True}
    )
    assert forged.status_code == 422
    response = await agent.client.post(path + "/verify", headers=agent.headers, json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "waiting" and not receipt["verification"]["satisfied"]
    evidence = receipt["verification"]["checks"][-1]["evidence_refs"]
    assert len(evidence) == 2 and all(
        p["blockers"] == ["DELIVERY_SESSION_MISSING"] for p in evidence
    )
    assert (
        await agent.client.post(path + "/verify", headers=agent.headers, json=body)
    ).json() == receipt
    assert len(calls) == 1
    assert (await agent.client.get(path)).json()["last_verification"] == receipt["verification"]
    for operation, status in (("pause", "paused"), ("resume", "waiting"), ("cancel", "cancelled")):
        command = {"expected_revision": receipt["result_revision"], "reason": "Synthetic control"}
        result = await agent.client.post(
            path + "/" + operation, headers=agent.headers, json=command
        )
        assert result.status_code == 200, result.text
        receipt = result.json()
        assert receipt["status"] == status and receipt["reason"] == command["reason"]
    archived = await agent.client.patch(
        path,
        headers=agent.headers,
        json={"expected_revision": receipt["result_revision"], "archived": True},
    )
    assert archived.status_code == 200 and archived.json()["archived_at"]
    assert (await agent.client.get(root)).json()["items"] == []
    history = (await agent.client.get(root, params={"include_archived": True})).json()["items"]
    assert len(history) == 1 and history[0]["id"] == goal["id"]
    assert len(calls) == 1
