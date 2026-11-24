"""HTTP contract for source-use declarations (API-S01 per-source slice)."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def test_source_use_http_defaults_declaration_replay_and_revocation(api):
    from uuid import uuid4

    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Source use")
    revision = uuid4()
    path = f"/api/v1/projects/{project}/file-revisions/{revision}/source-use"
    default = client.get(path)
    assert default.status_code == 200, default.text
    assert default.json() == {
        "subject_id": None,
        "version": 0,
        "current_revision_id": None,
        "state": "unreviewed",
        "allowed_uses": [],
        "statement": "",
        "evidence_note": "",
    }
    body = {
        "request_key": "declare-1",
        "expected_version": 0,
        "state": "declared",
        "allowed_uses": ["research"],
        "statement": "本人整理，可用于研究引用。",
        "evidence_note": "访谈记录",
    }
    assert client.put(path, json=body).status_code == 403
    created = client.put(path, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert created.status_code == 200, created.text
    receipt = created.json()
    assert receipt["result_version"] == 2 and receipt["state"] == "declared"
    replay = client.put(path, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert replay.status_code == 200 and replay.json() == receipt
    conflict = client.put(
        path,
        json={**body, "statement": "不同声明"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert conflict.status_code == 409
    current = client.get(path).json()
    assert current["state"] == "declared" and current["allowed_uses"] == ["research"]
    assert current["statement"] == "本人整理，可用于研究引用。"
    impact = client.get(
        f"/api/v1/projects/{project}/source-use-subjects/{current['subject_id']}/impact"
    )
    assert impact.json() == {"items": [], "next_cursor": None, "other_project_uses_count": 0}
    incomplete = client.put(
        path,
        json={**body, "request_key": "declare-2", "expected_version": 2, "statement": " "},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert incomplete.status_code == 422
    stale = client.put(
        path,
        json={**body, "request_key": "declare-3", "expected_version": 1},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stale.status_code == 409
    revoked = client.put(
        path,
        json={
            "request_key": "revoke-1",
            "expected_version": 2,
            "state": "revoked",
            "allowed_uses": [],
            "statement": "来源请求撤回",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert client.get(path).json()["state"] == "revoked"


def test_artifact_source_use_is_project_scoped(api):
    from uuid import uuid4

    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Artifact use")
    other = _project(client, workspace, "Other artifact use")
    artifact = str(uuid4())
    path = f"/api/v1/projects/{project}/artifacts/{artifact}/source-use"
    assert client.get(path).status_code == 404
    assert client.get(path.replace(project, other)).status_code == 404


def test_source_use_impact_http_defaults_and_unknown_subject(api):
    from uuid import uuid4

    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Impact")
    path = f"/api/v1/projects/{project}/source-use-subjects/{uuid4()}/impact"
    assert client.get(path).status_code == 404
