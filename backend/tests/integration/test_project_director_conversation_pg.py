"""Ordinary project chat survives reopening and carries selected context across turns."""

import json

import httpx
from test_director_agent_http_pg import _accept, _execute, _settle
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_project_conversation_reopens_with_history_and_current_shot(http_agent):
    a = http_agent
    scope = {"scope_type": "project", "scope_entity_id": str(a.project_id)}
    async def reads():
        return await a.client.get(a.threads_path, params=scope)

    initial = await reads()
    assert initial.status_code == 200 and initial.json() is None
    wrong = await a.client.get(a.threads_path, params={**scope, "scope_entity_id": str(a.shot_id)})
    assert wrong.status_code == 404
    thread = (await a.client.post(a.threads_path, headers=a.headers, json=scope)).json()
    assert (await reads()).json() == thread
    requests = []
    inputs = ["记住这场灯会的名字叫青石。", "现在选中镜头了，刚才那场灯会叫什么？"]
    answers = ["记下了，青石灯会。", "前面说的是青石灯会。"]

    async def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests) - 1
        messages = body["messages"]
        assert messages[-1]["content"] == inputs[index]
        if index == 1:
            assert [(m["role"], m["content"]) for m in messages[-3:]] == [
                ("user", inputs[0]),
                ("assistant", answers[0]),
                ("user", inputs[1]),
            ]
            assert any(
                str(a.shot_id) in m["content"] and "selected_context" in m["content"]
                for m in messages[:-3]
                if m["role"] == "system"
            )
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": answers[index]},
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    a.chat.handle = upstream
    for n, content in enumerate(inputs):
        data = {"content": content, "request_key": f"converse-{n}"}
        if n:
            data["ui_context"] = {"selected_refs": [{"kind": "shot", "id": str(a.shot_id)}]}
        accepted = await _accept(a, thread["id"], data)
        state = await _settle(a, thread["id"], accepted)
        assert state["turn"]["status"] == "completed", state
        assert state["turn"]["model_calls"] == 1
        replay = await _accept(a, thread["id"], data, expected_status=200)
        assert replay["turn_id"] == accepted["turn_id"]
        await _execute(a, accepted["turn_id"])
    reopened = (await reads()).json()["id"]
    transcript = (await a.client.get(f"{a.threads_path}/{reopened}")).json()
    assert [m["content"] for m in transcript["messages"]] == [
        inputs[0],
        answers[0],
        inputs[1],
        answers[1],
    ]
    denied = await a.client.get(
        a.threads_path, params=scope, headers={"X-Workspace-Id": str(a.other_workspace_id)}
    )
    assert denied.status_code == 404
    assert len(requests) == 2
