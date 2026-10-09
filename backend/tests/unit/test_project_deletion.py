"""Project deletion keeps history and removes access through the owner API."""

import asyncio
from uuid import UUID

from app.access.models import Project
from app.director.turn_models import DirectorTurn
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import select


def setup_project(client: TestClient) -> tuple[str, dict[str, object], dict[str, str]]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "delete-project@example.com",
            "password": "password123",
            "display_name": "Owner",
        },
    )
    assert response.status_code == 201
    workspace = client.get("/api/v1/workspaces").json()[0]["id"]
    client.headers["X-Workspace-Id"] = workspace
    headers = {CSRF_HEADER: client.get("/api/v1/auth/csrf").json()["csrf_token"]}
    response = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace,
            "name": "待删除的项目",
            "aspect_ratio": "9:16",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return workspace, response.json(), headers


def test_delete_removes_project_from_list_and_workbench_and_frees_name(client: TestClient) -> None:
    workspace, project, headers = setup_project(client)
    url = f"/api/v1/projects/{project['id']}"
    response = client.delete(url, params={"expected_version": project["version"]}, headers=headers)
    assert response.status_code == 204, response.text
    assert client.get(f"/api/v1/workspaces/{workspace}/projects").json() == []
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/snapshot").status_code == 404
    recreated = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace,
            "name": project["name"],
            "aspect_ratio": "9:16",
        },
        headers=headers,
    )
    assert recreated.status_code == 201, recreated.text
    assert recreated.json()["id"] != project["id"]


def test_delete_requires_csrf_and_current_version(client: TestClient) -> None:
    workspace, project, headers = setup_project(client)
    url = f"/api/v1/projects/{project['id']}"
    assert client.delete(url, params={"expected_version": project["version"]}).status_code == 403
    assert client.delete(url, params={"expected_version": 999}, headers=headers).status_code == 409
    assert len(client.get(f"/api/v1/workspaces/{workspace}/projects").json()) == 1


def test_delete_cannot_cross_workspace(client: TestClient) -> None:
    _, project, headers = setup_project(client)
    other = client.post("/api/v1/workspaces", json={"name": "另一空间"}, headers=headers)
    assert other.status_code == 201
    client.headers["X-Workspace-Id"] = other.json()["id"]
    response = client.delete(
        f"/api/v1/projects/{project['id']}",
        params={"expected_version": project["version"]},
        headers=headers,
    )
    assert response.status_code == 404


def test_delete_blocks_active_director_work_and_retains_completed_evidence(
    client: TestClient,
) -> None:
    workspace, project, headers = setup_project(client)
    owner_id = client.get("/api/v1/auth/me").json()["id"]

    async def save_turn() -> UUID:
        async for session in client.app.dependency_overrides[get_session]():
            turn = DirectorTurn(
                workspace_id=UUID(workspace),
                project_id=UUID(str(project["id"])),
                actor_id=UUID(owner_id),
                scope_type="project",
                scope_entity_id=UUID(str(project["id"])),
                request_key="delete-history-test",
                context_hash="a" * 64,
                status="thinking",
                output_snapshot={"frozen": "historical evidence"},
            )
            session.add(turn)
            await session.commit()
            return turn.id
        raise AssertionError("session unavailable")

    turn_id = asyncio.run(save_turn())
    url = f"/api/v1/projects/{project['id']}"
    response = client.delete(url, params={"expected_version": project["version"]}, headers=headers)
    assert response.status_code == 409
    assert response.json()["details"]["code"] == "PROJECT_ACTIVE_WORK"

    async def complete_and_check(deleted: bool = False) -> None:
        async for session in client.app.dependency_overrides[get_session]():
            turn = await session.get(DirectorTurn, turn_id)
            assert turn is not None
            assert turn.output_snapshot == {"frozen": "historical evidence"}
            if deleted:
                retained_project = await session.scalar(
                    select(Project).where(Project.id == UUID(str(project["id"])))
                )
                assert retained_project is not None and retained_project.deleted_at is not None
                assert turn.status == "completed"
            else:
                turn.status = "completed"
                await session.commit()

    asyncio.run(complete_and_check())
    assert (
        client.delete(
            url, params={"expected_version": project["version"]}, headers=headers
        ).status_code
        == 204
    )
    asyncio.run(complete_and_check(deleted=True))
