"""HTTP contract for project egress policy and workspace destinations (API-S01–04)."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def test_egress_policy_defaults_initialize_replay_and_conflict(api):
    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Egress")
    other = _project(client, workspace, "Other egress")
    path = f"/api/v1/projects/{project}/egress-policy"
    default = client.get(path)
    assert default.status_code == 200
    assert default.json() == {
        "revision": 0,
        "revision_id": None,
        "mode": "current",
        "allowed_destination_revision_ids": [],
        "allowed_purposes": [],
        "policy_hash": None,
    }
    # Writes require CSRF and are project-scoped.
    assert client.put(path, json={"expected_revision": 0, "mode": "local_only"}).status_code == 403
    created = client.put(
        path,
        json={"expected_revision": 0, "mode": "local_only"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 200, created.text
    assert created.json()["revision"] == 1 and created.json()["mode"] == "local_only"
    replay = client.put(
        path,
        json={"expected_revision": 0, "mode": "local_only"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert replay.json()["revision_id"] == created.json()["revision_id"]
    conflict = client.put(
        path,
        json={"expected_revision": 0, "mode": "current"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert conflict.status_code == 409
    assert conflict.json()["details"]["code"] == "EGRESS_REVISION_CONFLICT"
    # Another project keeps its own independent default.
    assert client.get(f"/api/v1/projects/{other}/egress-policy").json()["revision"] == 0
    # Invalid payloads never write.
    assert client.put(
        path,
        json={"expected_revision": 1, "mode": "local_only", "allowed_purposes": ["research_text"]},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 422
    assert client.put(
        path,
        json={"expected_revision": 1, "mode": "allowlisted"},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 422


def test_workspace_destination_registry_requires_real_binding(api):
    client, _factory = api
    workspace = _register(client)
    _project(client, workspace, "Destination")
    path = f"/api/v1/workspaces/{workspace}/provider-destinations"
    assert client.get(path).json() == []
    unknown = client.post(
        path,
        json={
            "binding_ref": "00000000-0000-0000-0000-000000000000",
            "expected_revision": 0,
            "expected_configuration_hash": "0" * 64,
            "processing_location": "external",
            "purposes": ["video_generation"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert unknown.status_code == 404
    invalid = client.post(
        path,
        json={
            "binding_ref": "not-a-binding",
            "expected_revision": 0,
            "expected_configuration_hash": "0" * 64,
            "processing_location": "external",
            "purposes": ["video_generation"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert invalid.status_code == 422
    assert invalid.json()["details"]["code"] == "DESTINATION_BINDING_INVALID"
    bad_origin = client.post(
        path,
        json={
            "binding_ref": "00000000-0000-0000-0000-000000000000",
            "expected_revision": 0,
            "expected_configuration_hash": "0" * 64,
            "processing_location": "external",
            "purposes": ["video_generation"],
            "additional_result_origins": ["https://*.example.com"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert bad_origin.status_code == 422
