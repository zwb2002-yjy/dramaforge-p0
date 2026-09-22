"""HTTP proofs for bounded reads: auth, workspace/project scope and limits."""

from uuid import uuid4

import pytest
from app.access.models import Workspace
from app.api.deps import get_current_user
from app.config import get_settings
from app.execution.shot_pipeline import SHOT_NODES
from app.main import create_app
from app.shared.db import get_session
from httpx import ASGITransport, AsyncClient
from tests.unit.test_production_bounded_reads import add_run
from tests.unit.test_scene_workspace_snapshot import _make_env, _seed


@pytest.fixture
async def http_env():
    engine, session = await _make_env()
    user, project, _, _, shot = await _seed(session)
    env = engine, session, user, project, shot
    run = await add_run(env, "completed", frozen_prompt="private production truth")
    foreign, other_project, _, _, other_shot = await _seed(session)
    other_run = await add_run((engine, session, foreign, other_project, other_shot))
    other_workspace = Workspace(owner_user_id=user.id, name="Another owned workspace")
    session.add(other_workspace)
    await session.flush()
    app = create_app(get_settings())

    async def get_test_session():
        yield session

    app.dependency_overrides[get_session] = get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app, user, project, run, other_workspace, other_project, other_run
    app.dependency_overrides.clear()
    await session.close()
    await engine.dispose()


@pytest.mark.parametrize(
    "suffix",
    [
        "production-summary",
        "node-runs/status",
        "production-history/runs",
        "production-history/artifacts",
    ],
)
async def test_read_routes_require_auth_and_exact_workspace_project(http_env, suffix):
    client, app, user, project, run, other_workspace, other_project, _ = http_env
    params = {"run_id": str(run.id)} if suffix == "node-runs/status" else {}
    url = f"/api/v1/projects/{project.id}/{suffix}"
    assert (await client.get(url, params=params)).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: user
    assert (await client.get(url, params=params)).status_code == 403
    mismatch = await client.get(
        url, params=params, headers={"X-Workspace-Id": str(other_workspace.id)}
    )
    # ProjectService deliberately hides projects outside the selected workspace.
    assert mismatch.status_code == 404
    foreign = await client.get(
        url, params=params, headers={"X-Workspace-Id": str(other_project.workspace_id)}
    )
    assert foreign.status_code == 403
    owner_headers = {"X-Workspace-Id": str(project.workspace_id)}
    foreign_project = await client.get(
        f"/api/v1/projects/{other_project.id}/{suffix}",
        params=params,
        headers=owner_headers,
    )
    assert foreign_project.status_code == 404
    response = await client.get(url, params=params, headers=owner_headers)
    assert response.status_code == 200
    if suffix == "production-summary":
        stages = response.json()["stages"]
        assert [stage["node_key"] for stage in stages] == list(SHOT_NODES)
        keyframe = next(stage for stage in stages if stage["node_key"] == "keyframe")
        assert keyframe["status_counts"] == {"completed": 1}
        assert keyframe["latest_failure"] is None
    assert "input_snapshot" not in response.text
    assert "private production truth" not in response.text


async def test_read_routes_validate_bounds_and_never_return_partial_statuses(http_env):
    client, app, user, project, run, _, _, other_run = http_env
    app.dependency_overrides[get_current_user] = lambda: user
    client.headers["X-Workspace-Id"] = str(project.workspace_id)
    root = f"/api/v1/projects/{project.id}"
    status_url = root + "/node-runs/status"
    assert (await client.get(status_url)).status_code == 422
    assert (await client.get(status_url, params=[("run_id", str(run.id))] * 101)).status_code == 422
    assert (await client.get(status_url, params={"run_id": "not-a-uuid"})).status_code == 422
    for missing_id in [uuid4(), other_run.id]:
        response = await client.get(
            status_url, params=[("run_id", str(run.id)), ("run_id", str(missing_id))]
        )
        assert response.status_code == 404
        assert str(run.id) not in response.text
    response = await client.get(status_url, params={"run_id": str(run.id)})
    assert response.json() == [
        {
                "id": str(run.id),
                "status": "completed",
                "result_artifact_id": str(run.result_artifact_id),
                "error_code": None,
            }
    ]
    for kind in ["runs", "artifacts"]:
        url = root + "/production-history/" + kind
        for params in [{"limit": 0}, {"limit": 101}, {"cursor": "invalid"}, {"cursor": "x" * 257}]:
            assert (await client.get(url, params=params)).status_code == 422
        page = await client.get(url, params={"limit": 1})
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1


async def test_audio_filter_is_explicit_read_only_and_validated(http_env):
    client, app, user, project, _, _, _, _ = http_env
    app.dependency_overrides[get_current_user] = lambda: user
    client.headers["X-Workspace-Id"] = str(project.workspace_id)
    path = f"/api/v1/projects/{project.id}/production-history/artifacts"
    unfiltered = await client.get(path)
    assert unfiltered.json()["items"]
    audio_only = await client.get(path, params={"usable_audio": "true"})
    assert audio_only.status_code == 200
    assert audio_only.json() == {"items": [], "next_cursor": None}
    assert (await client.get(path, params={"usable_audio": "not-a-boolean"})).status_code == 422
