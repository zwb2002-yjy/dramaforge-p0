"""Personal workspace project API tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": email.partition("@")[0]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _default_workspace_id(client: TestClient) -> str:
    response = client.get("/api/v1/workspaces")
    assert response.status_code == 200
    return str(response.json()[0]["id"])


def _select_workspace(client: TestClient, workspace_id: str) -> None:
    client.headers["X-Workspace-Id"] = workspace_id


def test_create_get_and_list_project_for_workspace_owner(client: TestClient) -> None:
    _register(client, "pm@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    project = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_id,
            "name": "ShowAlpha",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    body = project.json()
    assert body["workspace_id"] == workspace_id
    assert body["stage"] == "draft"
    assert client.get(f"/api/v1/projects/{body['id']}").status_code == 200
    listed = client.get(f"/api/v1/workspaces/{workspace_id}/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_other_user_cannot_read_project_or_list_owner_workspace(client: TestClient) -> None:
    _register(client, "owner2@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    created = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_id,
            "name": "Secret",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201
    _register(client, "intruder@example.com")
    _select_workspace(client, _default_workspace_id(client))
    assert client.get(f"/api/v1/projects/{created.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/workspaces/{workspace_id}/projects").status_code == 404


def test_workspace_with_project_cannot_be_deleted(client: TestClient) -> None:
    _register(client, "delete-owner@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    assert (
        client.post(
            "/api/v1/projects",
            json={
                "work_type": "serial_comic",
                "workspace_id": workspace_id,
                "name": "Retained",
                "aspect_ratio": "9:16",
            },
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 201
    )
    deleted = client.delete(
        f"/api/v1/workspaces/{workspace_id}", headers={CSRF_HEADER: _csrf(client)}
    )
    assert deleted.status_code == 422
    assert deleted.json()["code"] == "VALIDATION_ERROR"


def test_selected_workspace_blocks_same_owner_cross_workspace_project_access(
    client: TestClient,
) -> None:
    _register(client, "workspace-isolation@example.com")
    workspace_a = _default_workspace_id(client)
    workspace_b_response = client.post(
        "/api/v1/workspaces",
        json={"name": "Workspace B"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert workspace_b_response.status_code == 201
    workspace_b = str(workspace_b_response.json()["id"])

    _select_workspace(client, workspace_a)
    project_a = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_a,
            "name": "A",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project_a.status_code == 201, project_a.text

    _select_workspace(client, workspace_b)
    project_b = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_b,
            "name": "B",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project_b.status_code == 201, project_b.text
    project_b_id = str(project_b.json()["id"])

    _select_workspace(client, workspace_a)
    listed = client.get(f"/api/v1/workspaces/{workspace_a}/projects")
    assert [project["id"] for project in listed.json()] == [project_a.json()["id"]]
    assert client.get(f"/api/v1/projects/{project_b_id}").status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_b_id}/brief",
        json={"logline": "must not update", "tone": "", "audience": ""},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 404
    # Production reads retain workspace ACLs after public queue helpers retire.
    assert client.get(f"/api/v1/projects/{project_b_id}/snapshot").status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_b_id}/exports/{uuid4()}/download-grant",
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 404

    _select_workspace(client, workspace_b)
    assert client.get(f"/api/v1/projects/{project_b_id}").status_code == 200
    assert client.get(f"/api/v1/projects/{project_b_id}/snapshot").status_code == 200


def _institution_owner(client: TestClient) -> tuple[str, dict[str, str]]:
    _register(client, f"intent-{uuid4().hex}@example.com")
    workspace = _default_workspace_id(client)
    _select_workspace(client, workspace)
    return workspace, {CSRF_HEADER: _csrf(client)}


@pytest.mark.parametrize("kind,count", [
    ("animation_promo", None), ("single_comic", 1), ("serial_comic", 3),
])
def test_institution_intent_round_trips_in_project_and_list(client, kind, count):
    workspace, headers = _institution_owner(client)
    response = client.post("/api/v1/projects", headers=headers, json={
        "workspace_id": workspace, "name": "机构作品", "aspect_ratio": "16:9",
        "work_type": kind, "creative_goal": "介绍古城的地方文化", "audience": "社区观众",
        "planned_duration_seconds": "35.125", "planned_episode_count": count,
    })
    assert response.status_code == 201, response.text
    created = response.json()
    for body in (
        created, client.get(f"/api/v1/projects/{created['id']}").json(),
        client.get(f"/api/v1/workspaces/{workspace}/projects").json()[0],
    ):
        assert body["work_type"] == kind
        assert body["creative_goal"] == "介绍古城的地方文化"
        assert body["audience"] == "社区观众"
        assert body["planned_duration_seconds"] == "35.125"
        assert body["planned_episode_count"] == count


@pytest.mark.parametrize("changes", [
    {}, {"work_type": None}, {"work_type": "unknown"},
    {"work_type": "single_comic", "planned_episode_count": 2},
    {"work_type": "serial_comic", "planned_episode_count": 1},
    {"work_type": "animation_promo", "planned_episode_count": 1},
    {"work_type": "serial_comic", "planned_episode_count": True},
    {"work_type": "serial_comic", "planned_episode_count": 2147483648},
    *({"work_type": "animation_promo", "planned_duration_seconds": value}
      for value in ("0", "-1", "NaN", "Infinity", "1.0001", "1000000000", 1.5)),
    {"work_type": "animation_promo", "creative_goal": "文" * 16001},
    {"work_type": "animation_promo", "audience": "人" * 2001},
    {"work_type": "animation_promo", "budget_limit": "100"},
])
def test_invalid_institution_intent_is_rejected_without_creating_a_project(client, changes):
    workspace, headers = _institution_owner(client)
    response = client.post("/api/v1/projects", headers=headers, json={
        "workspace_id": workspace, "name": "无效计划", "aspect_ratio": "16:9", **changes,
    })
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/workspaces/{workspace}/projects").json() == []


def test_project_intent_cas_partial_update_and_conflict_preserve_saved_fields(client):
    workspace, headers = _institution_owner(client)
    response = client.post("/api/v1/projects", headers=headers, json={
        "workspace_id": workspace, "name": "原项目", "aspect_ratio": "16:9",
        "work_type": "single_comic", "creative_goal": "原目标", "audience": "原受众",
    })
    assert response.status_code == 201, response.text
    project = response.json()
    path = f"/api/v1/projects/{project['id']}"
    updated = client.patch(path, headers=headers, json={
        "expected_version": 1, "name": " 新名称 ", "creative_goal": "新目标",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["name"] == "新名称"
    assert updated.json()["creative_goal"] == "新目标"
    assert updated.json()["audience"] == "原受众"
    assert updated.json()["creative_profile"] == project["creative_profile"]
    stale = client.patch(path, headers=headers, json={
        "expected_version": 1, "creative_goal": "过期覆盖",
    })
    assert stale.status_code == 409
    assert stale.json()["details"]["current_version"] == 2
    refused = client.patch(path, headers=headers, json={
        "expected_version": 2, "planned_episode_count": 2,
    })
    assert refused.status_code == 422
    assert client.patch(path, headers=headers, json={
        "expected_version": 2, "work_type": None,
    }).status_code == 422
    current = client.get(path).json()
    assert current["version"] == 2 and current["creative_goal"] == "新目标"
    unchanged = client.patch(path, headers=headers, json={
        "expected_version": 2, "creative_goal": "新目标",
    })
    assert unchanged.status_code == 200 and unchanged.json()["version"] == 2
    _register(client, f"other-{uuid4().hex}@example.com")
    _select_workspace(client, _default_workspace_id(client))
    assert client.patch(path, headers={CSRF_HEADER: _csrf(client)}, json={
        "expected_version": 2, "creative_goal": "越权覆盖",
    }).status_code == 404


async def _project_in_session(session):
    from app.access.models import User, Workspace
    from app.access.projects import ProjectService

    actor = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="fixture")
    session.add(actor)
    await session.flush()
    workspace = Workspace(owner_user_id=actor.id, name="机构")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id, actor=actor, name="作品", aspect_ratio="16:9",
        work_type="animation_promo",
    )
    await session.commit()
    return actor, project


async def test_project_change_notice_is_typed_and_contains_no_creative_text(session):
    from app.api.v1.projects import ProjectUpdate, preview_project_update, update_project
    from app.contracts.domain_events import ProductionEvent, ProjectChanged
    from app.director.inbox import receive_production_event
    from app.events.models import EventLog, OutboxEvent
    from sqlalchemy import func, select

    actor, project = await _project_in_session(session)
    body = ProjectUpdate(expected_version=1, creative_goal="私有目标文字")
    preview = await preview_project_update(
        project_id=project.id, body=body, user=actor, session=session, _=None,
    )
    assert preview.can_apply and preview.episode_count == 0
    assert project.creative_goal == "" and project.version == 1
    assert await session.scalar(select(func.count()).select_from(EventLog)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    updated = await update_project(
        project_id=project.id, body=body,
        user=actor, session=session, _=None,
    )
    assert updated.version == 2
    event = (await session.scalars(select(EventLog))).one()
    outbox = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_id == outbox.event_id
    assert outbox.topic == "production.facts.v1"
    assert "私有目标文字" not in str(event.payload)
    parsed = ProductionEvent.model_validate({
        "schema_version": event.schema_version, "event_id": event.event_id,
        "actor_id": event.actor_id, "project_id": event.project_id,
        "payload": event.payload["notice"],
    })
    assert isinstance(parsed.payload, ProjectChanged) and parsed.payload.project_version == 2
    assert await receive_production_event(session, project_id=project.id, event_id=event.event_id)


async def test_project_type_preview_reports_delivery_conflict_without_changing_it(session):
    from app.api.v1.projects import ProjectUpdate, preview_project_update, update_project
    from app.delivery.models import Export
    from app.events.models import EventLog
    from app.shared.errors import ConflictError
    from sqlalchemy import func, select

    actor, project = await _project_in_session(session)
    export = Export(project_id=project.id, requested_by=actor.id, status="queued", manifest={})
    session.add(export)
    await session.commit()
    body = ProjectUpdate(expected_version=1, work_type="single_comic")
    impact = await preview_project_update(
        project_id=project.id, body=body, user=actor, session=session, _=None,
    )
    assert not impact.can_apply and impact.affected_export_id == export.id
    assert impact.blockers
    assert project.work_type == "animation_promo" and project.version == 1
    assert export.episode_id is None and export.status == "queued"
    assert await session.scalar(select(func.count()).select_from(EventLog)) == 0
    with pytest.raises(ConflictError) as caught:
        await update_project(project_id=project.id, body=body, user=actor, session=session, _=None)
    assert caught.value.details["code"] == "PROJECT_STRUCTURE_CONFLICT"
    assert project.work_type == "animation_promo" and export.status == "queued"
