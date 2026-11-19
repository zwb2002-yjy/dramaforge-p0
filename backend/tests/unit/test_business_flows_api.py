"""HTTP read projection for BusinessFlow instances, steps and attempts."""

from __future__ import annotations

from test_director_turn_api import _project, _register
from test_director_turn_api import api as api


def test_business_flow_read_projection_scopes_every_level(api):
    from uuid import uuid4

    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Flows")
    other = _project(client, workspace, "Other flows")
    flow = uuid4()
    run = uuid4()
    flow_path = f"/api/v1/projects/{project}/director/business-flows/{flow}"
    assert client.get(flow_path).status_code == 404
    other_path = f"/api/v1/projects/{other}/director/business-flows/{flow}"
    assert client.get(other_path).status_code == 404
    assert client.get(
        f"/api/v1/projects/{project}/director/business-flows/{flow}/steps"
    ).status_code == 404
    assert client.get(
        f"/api/v1/projects/{project}/director/business-flows/{flow}/steps/{uuid4()}/attempts"
    ).status_code == 404
    # The run-scoped list requires the run to exist for this project.
    assert client.get(
        f"/api/v1/projects/{project}/director/master-runs/{run}/business-flows"
    ).status_code == 404
