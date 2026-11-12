"""HTTP proofs for qualified production run cancellation."""

from __future__ import annotations

import pytest
from app.access.models import Workspace
from app.api.deps import get_current_user
from app.config import get_settings
from app.main import create_app
from app.shared.db import get_session
from app.shared.security import CSRF_COOKIE, CSRF_HEADER, issue_csrf_token
from httpx import ASGITransport, AsyncClient
from tests.unit.test_production_bounded_reads import add_run
from tests.unit.test_scene_workspace_snapshot import _make_env, _seed


@pytest.fixture
async def http_env():
    engine, session = await _make_env()
    user, project, _, _, shot = await _seed(session)
    env = engine, session, user, project, shot
    other_workspace = Workspace(owner_user_id=user.id, name="Another owned workspace")
    session.add(other_workspace)
    await session.flush()
    app = create_app(get_settings())

    async def get_test_session():
        yield session

    app.dependency_overrides[get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app, session, user, project, env
    app.dependency_overrides.clear()
    await session.close()
    await engine.dispose()


class _Cancellation:
    """Authenticated, CSRF-paired caller for the cancel route."""

    def __init__(self, client: AsyncClient, app, user, project) -> None:
        self._client = client
        self._app = app
        self._user = user
        self._project = project
        self.token = issue_csrf_token(secret=get_settings().session_secret)
        client.cookies.set(CSRF_COOKIE, self.token)

    async def cancel(self, run_id, *, project_id=None):
        self._app.dependency_overrides[get_current_user] = lambda: self._user
        return await self._client.post(
            f"/api/v1/projects/{project_id or self._project.id}/node-runs/{run_id}/cancel",
            headers={CSRF_HEADER: self.token, "X-Workspace-Id": str(self._project.workspace_id)},
        )


@pytest.mark.asyncio
async def test_cancel_requires_auth_and_csrf(http_env) -> None:
    client, app, _, user, project, env = http_env
    run = await add_run(env, "queued")
    url = f"/api/v1/projects/{project.id}/node-runs/{run.id}/cancel"

    assert (await client.post(url)).status_code == 401

    app.dependency_overrides[get_current_user] = lambda: user
    headers = {"X-Workspace-Id": str(project.workspace_id)}
    assert (await client.post(url, headers=headers)).status_code == 403

    caller = _Cancellation(client, app, user, project)
    response = await caller.cancel(run.id)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_cancel_queued_run_finishes_before_submission(http_env) -> None:
    client, app, _, user, project, env = http_env
    run = await add_run(env, "queued")
    response = await _Cancellation(client, app, user, project).cancel(run.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_requested_at"] is not None


@pytest.mark.asyncio
async def test_cancel_running_run_requests_cancellation_idempotently(http_env) -> None:
    client, app, _, user, project, env = http_env
    run = await add_run(env, "running")
    caller = _Cancellation(client, app, user, project)

    first = await caller.cancel(run.id)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "cancel_requested"

    second = await caller.cancel(run.id)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "cancel_requested"


@pytest.mark.asyncio
async def test_cancel_rejects_terminal_run(http_env) -> None:
    client, app, _, user, project, env = http_env
    run = await add_run(env, "completed")
    response = await _Cancellation(client, app, user, project).cancel(run.id)

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_cancel_hides_foreign_project(http_env) -> None:
    client, app, _, user, project, env = http_env
    _, other_project, _, _, other_shot = await _seed(env[1])
    foreign_run = await add_run((env[0], env[1], user, other_project, other_shot), "queued")

    response = await _Cancellation(client, app, user, project).cancel(
        foreign_run.id, project_id=other_project.id
    )
    assert response.status_code == 404
