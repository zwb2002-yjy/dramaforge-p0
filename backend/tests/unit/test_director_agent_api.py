"""Agent HTTP admission, scoped sessions and synchronous receipt contracts."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.api.v1 import director
from app.director.agent_service import AgentTurnResult
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.security import CSRF_HEADER
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


@pytest.fixture
def agent_http(monkeypatch):
    calls = []
    receipt = AgentTurnResult(
        turn_id=uuid4(),
        thread_id=uuid4(),
        status="completed",
        transport_status="succeeded",
        assistant_message_id=uuid4(),
        usage={"total_tokens": 12},
        model_calls=2,
        tool_calls=1,
        version=3,
    )
    state = {"replay": None, "receipt": receipt, "calls": calls, "sessions": []}
    original_authorize = director.ProjectService.get_project_for_owner

    async def authorize(self, **kwargs):
        result = await original_authorize(self, **kwargs)
        state["sessions"].append(self._session)
        return result

    monkeypatch.setattr(director.ProjectService, "get_project_for_owner", authorize)

    class Service:
        def __init__(self, factory, *, actor_id, workspace_id, project_id, model_tools=None):
            assert factory.kw["expire_on_commit"] is False
            assert isinstance(model_tools, director.ApiDirectorModelTools)
            self.project_id = project_id
            calls.append(("service", actor_id, workspace_id, project_id))

        def assert_released(self):
            assert not state["sessions"][-1].in_transaction()

        async def open_thread(self, body):
            self.assert_released()
            calls.append(("open", body.scope_type))
            return SimpleNamespace(
                id=receipt.thread_id,
                scope_type=body.scope_type,
                scope_entity_id=body.scope_entity_id or self.project_id,
            )

        async def read_thread(self, thread_id, *, limit, offset):
            self.assert_released()
            calls.append(("read", thread_id, limit, offset))
            if thread_id != receipt.thread_id:
                raise NotFoundError("Director thread not found")
            return {
                "id": thread_id,
                "scope_type": "project",
                "scope_entity_id": self.project_id,
                "messages": [
                    {
                        "id": receipt.assistant_message_id,
                        "turn_id": receipt.turn_id,
                        "role": "assistant",
                        "content": "Read the selected shot.",
                        "created_at": datetime.now(UTC),
                    }
                ],
                "offset": offset or 0,
                "limit": limit,
                "total": (offset or 0) + 1,
                "has_more": False,
                "has_previous": bool(offset),
            }

        async def read_request(self, thread_id, request_key):
            self.assert_released()
            calls.append(("receipt", thread_id, request_key))
            return receipt

        async def replay(self, thread_id, request):
            self.assert_released()
            calls.append(("replay", thread_id, request.request_key))
            return state["replay"]

        async def run(self, thread_id, request, *, checkpointer):
            self.assert_released()
            assert checkpointer is state["checkpointer"]
            calls.append(("run", thread_id, request.request_key))
            return receipt

        async def stop(self, turn_id, *, expected_revision, request_key):
            self.assert_released()
            calls.append(("stop", turn_id, expected_revision, request_key))
            return receipt.model_copy(update={"status": "cancelled", "stop_reason": "user_stop"})

    monkeypatch.setattr(director, "DirectorAgentService", Service)

    def available(settings):
        calls.append(("availability",))

    @asynccontextmanager
    async def checkpoint(settings, *, project_id):
        calls.append(("checkpoint_open", project_id))
        state["checkpointer"] = object()
        try:
            yield state["checkpointer"]
        finally:
            calls.append(("checkpoint_closed",))

    monkeypatch.setattr(director, "require_director_runtime_available", available)
    monkeypatch.setattr(director, "scoped_checkpointer", checkpoint)
    return state


def test_agent_thread_endpoints_are_scoped_paginated_and_csrf_protected(api, agent_http):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Agent API")
    base = f"/api/v1/projects/{project_id}/director/threads"
    denied = client.post(base, json={"scope_type": "project"})
    assert denied.status_code == 403
    assert agent_http["calls"] == []
    created = client.post(base, json={}, headers={CSRF_HEADER: _csrf(client)})
    assert created.status_code == 201, created.text
    assert created.json() == {
        "id": str(agent_http["receipt"].thread_id),
        "scope_type": "project",
        "scope_entity_id": project_id,
    }
    thread_path = base + "/" + created.json()["id"]
    read = client.get(thread_path, params={"limit": 5, "offset": 2})
    assert read.status_code == 200, read.text
    assert read.json()["limit"] == 5 and read.json()["offset"] == 2
    assert read.json()["messages"][0]["turn_id"] == str(agent_http["receipt"].turn_id)
    assert client.get(thread_path, params={"limit": 101}).status_code == 422
    assert client.get(thread_path, params={"offset": -1}).status_code == 422
    assert client.get(base + "/" + str(uuid4())).status_code == 404
    before = len(agent_http["calls"])
    wrong_project = client.post(
        f"/api/v1/projects/{uuid4()}/director/threads",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert wrong_project.status_code == 404
    assert len(agent_http["calls"]) == before
    service = next(call for call in agent_http["calls"] if call[0] == "service")
    assert service[2:] == (UUID(workspace_id), UUID(project_id))


def test_agent_endpoints_require_authentication(api, agent_http):
    client, _ = api
    base = f"/api/v1/projects/{uuid4()}/director/threads"
    assert client.post(base, json={}).status_code == 401
    assert client.get(base + "/" + str(uuid4())).status_code == 401
    assert agent_http["calls"] == []


def test_agent_request_receipt_uses_read_only_query_with_full_key(api, agent_http):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Read receipt")
    thread_id = agent_http["receipt"].thread_id
    key = "agent/request ? 中文"
    response = client.get(
        f"/api/v1/projects/{project_id}/director/threads/{thread_id}/requests",
        params={"request_key": key},
    )
    assert response.status_code == 200
    assert response.json() == agent_http["receipt"].model_dump(mode="json")
    assert agent_http["calls"][-1] == ("receipt", thread_id, key)
    assert not any(
        call[0] in {"run", "replay", "availability", "checkpoint_open"}
        for call in agent_http["calls"]
    )


def test_agent_message_returns_synchronous_result_and_closes_scoped_checkpoint(api, agent_http):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Agent message")
    receipt = agent_http["receipt"]
    path = f"/api/v1/projects/{project_id}/director/threads/{receipt.thread_id}/messages"
    body = {"content": "Read this project", "request_key": "agent-message-1"}
    assert client.post(path, json=body).status_code == 403
    response = client.post(path, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert response.status_code == 200, response.text
    assert response.json() == receipt.model_dump(mode="json")
    assert [call[0] for call in agent_http["calls"]] == [
        "service",
        "replay",
        "availability",
        "checkpoint_open",
        "run",
        "checkpoint_closed",
    ]
    assert ("checkpoint_open", UUID(project_id)) in agent_http["calls"]


def test_completed_replay_does_not_need_runtime_or_checkpoint(api, agent_http, monkeypatch):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Agent replay")
    receipt = agent_http["receipt"]
    agent_http["replay"] = receipt

    def unavailable(settings):
        pytest.fail("replay must not require a model or checkpoint")

    monkeypatch.setattr(director, "require_director_runtime_available", unavailable)
    response = client.post(
        f"/api/v1/projects/{project_id}/director/threads/{receipt.thread_id}/messages",
        json={"content": "Read this project", "request_key": "agent-replay"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 200
    assert [call[0] for call in agent_http["calls"]] == ["service", "replay"]


def test_new_message_fails_closed_before_checkpoint_or_run(api, agent_http, monkeypatch):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Agent unavailable")

    def unavailable(settings):
        raise ValidationAppError("Director runtime unavailable")

    monkeypatch.setattr(director, "require_director_runtime_available", unavailable)
    thread_id = agent_http["receipt"].thread_id
    response = client.post(
        f"/api/v1/projects/{project_id}/director/threads/{thread_id}/messages",
        json={"content": "Read this project", "request_key": "agent-unavailable"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 422
    assert [call[0] for call in agent_http["calls"]] == ["service", "replay"]


def test_agent_stop_uses_business_revision_and_request_key_without_checkpoint(api, agent_http):
    client, _ = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Agent stop")
    turn_id = agent_http["receipt"].turn_id
    path = f"/api/v1/projects/{project_id}/director/agent/turns/{turn_id}/stop"
    body = {"expected_revision": 3, "request_key": "stop-agent-1"}
    assert client.post(path, json=body).status_code == 403
    stopped = client.post(path, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "cancelled"
    assert stopped.json()["stop_reason"] == "user_stop"
    assert ("stop", turn_id, 3, "stop-agent-1") in agent_http["calls"]
    assert all(call[0] not in {"availability", "checkpoint_open"} for call in agent_http["calls"])
