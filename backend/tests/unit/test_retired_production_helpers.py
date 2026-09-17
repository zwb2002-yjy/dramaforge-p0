"""Execution/repair commands and resident dispatch replace public queue helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

RETIRED_PATHS = (
    "/api/v1/projects/{project_id}/dispatch",
    "/api/v1/projects/{project_id}/node-runs/{node_run_id}/enqueue",
)


@pytest.mark.parametrize("path", RETIRED_PATHS)
def test_queue_helper_absent_from_openapi(bare_client: TestClient, path: str) -> None:
    response = bare_client.get("/openapi.json")
    assert response.status_code == 200
    assert path not in response.json()["paths"]


@pytest.mark.parametrize("path", RETIRED_PATHS)
def test_queue_helper_http_route_is_absent(bare_client: TestClient, path: str) -> None:
    # No login/DB: a removed route must be a routing 404, not an ACL rejection.
    response = bare_client.post(path.format(project_id=uuid4(), node_run_id=uuid4()))
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Not Found"


def test_retained_production_workflows_remain_in_openapi(bare_client: TestClient) -> None:
    response = bare_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    # User intent belongs to execution/repair commands, not raw queue operations.
    assert "post" in paths["/api/v1/projects/{project_id}/shots/{shot_id}/executions"]
    assert "post" in paths[
        "/api/v1/projects/{project_id}/shots/{shot_id}/repairs/{repair_id}/steps"
    ]
    assert "get" in paths["/api/v1/projects/{project_id}/snapshot"]
    # Video frame evidence is still needed for human review; it is not retired.
    assert "get" in paths[
        "/api/v1/projects/{project_id}/artifacts/{artifact_id}/video-frames/{role}"
    ]
