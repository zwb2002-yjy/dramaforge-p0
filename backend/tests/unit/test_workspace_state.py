"""P1-01 workspace state API tests."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient

SCRIPT = (
    "# Episode 1 — 晚风\n\n"
    "## Scene 1 — 天台 / night\n"
    "synopsis\n\n"
    "### Shot 1 — medium\n"
    "Visual: 主角站在天台上。\n"
    "Dialogue: 今晚就到这里。\n"
)


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"workspace-state-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Workspace Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _create_project(client: TestClient, workspace_id: str, name: str) -> str:
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": name, "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return str(created.json()["id"])


def _project(client: TestClient) -> str:
    return _create_project(client, _register(client), "State Project")


def _imported_shot(client: TestClient, project_id: str, filename: str) -> str:
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={"filename": filename, "text": SCRIPT},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code in {200, 201}, imported.text
    return str(imported.json()["shot_ids"][0])


def test_workspace_state_defaults_empty_and_round_trips(client: TestClient) -> None:
    project_id = _project(client)
    initial = client.get(f"/api/v1/projects/{project_id}/workspace-state")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {"state": {}}

    updated = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={
            "state": {
                "last_view": "scenes",
                "selected_scene_id": None,
                "panels": {"inspector": True},
            }
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"]["last_view"] == "scenes"
    assert updated.json()["state"]["panels"] == {"inspector": True}

    reread = client.get(f"/api/v1/projects/{project_id}/workspace-state")
    assert reread.status_code == 200, reread.text
    assert reread.json() == updated.json()


def test_workspace_state_patch_merges_partial(client: TestClient) -> None:
    project_id = _project(client)
    first = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"last_view": "assets"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert first.status_code == 200, first.text
    merged = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"selected_shot_id": None, "panels": {"inspector": True}}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["state"] == {
        "last_view": "assets",
        "selected_shot_id": None,
        "panels": {"inspector": True},
    }


def test_workspace_state_round_trips_a_shot_of_this_project(client: TestClient) -> None:
    project_id = _project(client)
    shot_id = _imported_shot(client, project_id, "own.md")
    stored = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"selected_shot_id": shot_id, "last_view": "scenes"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["state"]["selected_shot_id"] == shot_id
    reread = client.get(f"/api/v1/projects/{project_id}/workspace-state")
    assert reread.json()["state"]["selected_shot_id"] == shot_id


def test_workspace_state_refuses_a_foreign_shot_selection(client: TestClient) -> None:
    """A client may clear a selection but never persist another project's ID."""
    project_id = _project(client)
    # Same workspace, second project: the ID exists and is readable, so only the
    # ownership reconciliation can reject it.
    other_project_id = _create_project(client, str(client.headers["X-Workspace-Id"]), "Other")
    foreign_shot_id = _imported_shot(client, other_project_id, "other.md")

    rejected = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"selected_shot_id": foreign_shot_id}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["details"]["code"] == "WORKSPACE_STATE_SELECTION_FOREIGN"
    # The rejected patch must not have been persisted.
    assert client.get(f"/api/v1/projects/{project_id}/workspace-state").json() == {"state": {}}

    malformed = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"selected_shot_id": "not-a-uuid"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert malformed.status_code == 422, malformed.text
    assert malformed.json()["details"]["code"] == "WORKSPACE_STATE_SELECTION_INVALID"


async def test_workspace_state_drops_a_selection_that_no_longer_resolves() -> None:
    """A stored pointer must not survive the Shot it names.

    Exercises the service directly so the test can delete the Shot rather than
    pretend it never existed: read reconciliation is what keeps a stale restore
    pointer from being replayed after the user deletes a scene or shot.
    """
    from app.access.models import User, Workspace
    from app.access.projects import ProjectService
    from app.assets.models import Shot
    from app.assets.script_import import import_script
    from app.shared.base import Base
    from app.shared.security import hash_password
    from app.workbench.workspace_state_service import WorkspaceStateService
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            owner = User(
                email=f"state-{uuid4().hex[:8]}@example.com",
                display_name="State Owner",
                password_hash=hash_password("password123"),
            )
            session.add(owner)
            await session.flush()
            workspace = Workspace(owner_user_id=owner.id, name=f"WS-{uuid4().hex[:6]}")
            session.add(workspace)
            await session.flush()
            project = await ProjectService(session).create_project(
                workspace_id=workspace.id,
                actor=owner,
                name="恢复项目",
                aspect_ratio="16:9",
            )
            imported = await import_script(
                session,
                project_id=project.id,
                actor_id=owner.id,
                actor=owner,
                filename="own.md",
                text=SCRIPT,
            )
            shot_id = imported.shot_ids[0]

            service = WorkspaceStateService(session)
            stored = await service.update_workspace_state(
                project_id=project.id,
                actor=owner,
                state={"selected_shot_id": str(shot_id), "last_view": "scenes"},
            )
            assert stored["selected_shot_id"] == str(shot_id)

            await session.execute(delete(Shot).where(Shot.id == shot_id))
            await session.flush()

            releaded = await service.get_workspace_state(project_id=project.id, actor=owner)
            assert "selected_shot_id" not in releaded
            # Dropping the pointer must not reset the unrelated view state.
            assert releaded["last_view"] == "scenes"
    finally:
        await engine.dispose()


def test_workspace_state_is_scoped_to_the_owning_user(client: TestClient) -> None:
    project_id = _project(client)
    client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"last_view": "edit"}},
        headers={CSRF_HEADER: _csrf(client)},
    ).raise_for_status()

    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(client.get("/api/v1/workspaces").json()[0]["id"])
    assert client.get(f"/api/v1/projects/{project_id}/workspace-state").status_code == 404
    assert (
        client.patch(
            f"/api/v1/projects/{project_id}/workspace-state",
            json={"state": {"last_view": "edit"}},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 404
    )
