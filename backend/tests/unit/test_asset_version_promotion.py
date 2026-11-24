"""P2-01 AssetVersion lifecycle promotion tests (API level).

Candidate creation and promotion are explicit keyed decisions: both require the
expected Asset row version, return a fixed receipt, replay the original receipt for
the same key, and refuse stale or repeated decisions.
"""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_and_asset(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"promote-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Promote Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_id,
            "name": "Promote Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    asset = client.post(
        f"/api/v1/projects/{project_id}/assets",
        json={"kind": "character", "name": "林墨", "description": "lead", "status": "active"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert asset.status_code == 201, asset.text
    return project_id, str(asset.json()["id"])


def _asset_version(client: TestClient, project_id: str, asset_id: str) -> int:
    card = client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/card")
    assert card.status_code == 200, card.text
    return int(card.json()["version"])


def _candidate(
    client: TestClient,
    project_id: str,
    asset_id: str,
    *,
    name: str,
    key: str,
    expected: int | None = None,
) -> object:
    version = expected if expected is not None else _asset_version(client, project_id, asset_id)
    return client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
        json={"request_key": key, "expected_asset_version": version, "name": name},
        headers={CSRF_HEADER: _csrf(client)},
    )


def _promote(
    client: TestClient,
    project_id: str,
    asset_id: str,
    version_id: str,
    *,
    expected: int,
    key: str,
) -> object:
    return client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{version_id}/promote",
        json={"request_key": key, "expected_asset_version": expected},
        headers={CSRF_HEADER: _csrf(client)},
    )


def test_create_promote_and_reject_lifecycle(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    candidate = _candidate(
        client, project_id, asset_id, name="林墨·成年", key="candidate-v2"
    )
    assert candidate.status_code == 201, candidate.text
    candidate_id = candidate.json()["asset_version_id"]
    assert candidate.json()["version_number"] == 2
    replay = _candidate(
        client,
        project_id,
        asset_id,
        name="林墨·成年",
        key="candidate-v2",
        expected=1,
    )
    assert replay.status_code == 200
    assert replay.json()["asset_version_id"] == candidate_id

    expected = _asset_version(client, project_id, asset_id)
    promoted = _promote(
        client, project_id, asset_id, candidate_id, expected=expected, key="adopt-v2"
    )
    assert promoted.status_code == 201, promoted.text
    receipt = promoted.json()
    assert receipt["asset_version_id"] == candidate_id
    assert receipt["accepted_asset_revision"] == expected + 1
    assert receipt["publication_id"] is None
    replay_promote = _promote(
        client, project_id, asset_id, candidate_id, expected=expected, key="adopt-v2"
    )
    assert replay_promote.status_code == 200
    assert replay_promote.json() == receipt
    second_key = _promote(
        client, project_id, asset_id, candidate_id, expected=expected, key="adopt-v2-again"
    )
    assert second_key.status_code == 409
    assert second_key.json()["details"]["code"] == "ASSET_VERSION_ALREADY_ADOPTED"

    card = client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/card")
    assert card.status_code == 200, card.text
    assert card.json()["current_version_id"] == candidate_id
    assert card.json()["current_version_status"] == "formal"

    rejected = _candidate(client, project_id, asset_id, name="bad idea", key="candidate-bad")
    rejected_id = rejected.json()["asset_version_id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{rejected_id}/reject",
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 200
    # A rejected candidate cannot be promoted.
    rejected_promote = _promote(
        client,
        project_id,
        asset_id,
        rejected_id,
        expected=_asset_version(client, project_id, asset_id),
        key="adopt-rejected",
    )
    assert rejected_promote.status_code == 422, rejected_promote.text


def test_promote_keeps_only_one_formal_and_never_deletes(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    v2 = _candidate(client, project_id, asset_id, name="v2", key="candidate-2").json()
    first = _promote(
        client,
        project_id,
        asset_id,
        v2["asset_version_id"],
        expected=_asset_version(client, project_id, asset_id),
        key="adopt-2",
    )
    assert first.status_code == 201, first.text
    v3 = _candidate(client, project_id, asset_id, name="v3", key="candidate-3").json()
    second = _promote(
        client,
        project_id,
        asset_id,
        v3["asset_version_id"],
        expected=_asset_version(client, project_id, asset_id),
        key="adopt-3",
    )
    assert second.status_code == 201, second.text

    history = client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/versions").json()
    versions = [item for item in history if item["status"] in {"formal", "historical"}]
    assert sum(1 for item in versions if item["status"] == "formal") == 1
    assert any(
        item["id"] == v2["asset_version_id"] and item["status"] == "historical"
        for item in history
    )
    assert any(
        item["id"] == v3["asset_version_id"] and item["status"] == "formal"
        for item in history
    )
    # No version is deleted.
    assert len(history) == 3


def test_promote_rejects_a_stale_expected_version(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    v2 = _candidate(client, project_id, asset_id, name="v2", key="candidate-stale").json()
    stale = _promote(
        client,
        project_id,
        asset_id,
        v2["asset_version_id"],
        expected=99,
        key="adopt-stale",
    )
    assert stale.status_code == 409
    assert stale.json()["details"]["code"] == "ASSET_STALE_VERSION"
    stale_candidate = _candidate(
        client, project_id, asset_id, name="stale", key="candidate-stale-2", expected=99
    )
    assert stale_candidate.status_code == 409
    assert stale_candidate.json()["details"]["code"] == "ASSET_STALE_VERSION"


def test_asset_version_cross_project_is_isolated(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"intruder-promote-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(client.get("/api/v1/workspaces").json()[0]["id"])
    assert (
        client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/versions").status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
            json={"request_key": "stolen", "expected_asset_version": 1, "name": "stolen"},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 404
    )
