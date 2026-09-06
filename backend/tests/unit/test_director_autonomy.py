"""V1 G3A DirectorAutonomy backend tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.director.autonomy_policy import DirectorAutonomyPolicy, policy_for
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def test_policy_matrix_matches_design() -> None:
    auto = policy_for("AUTO")
    assist = policy_for("ASSIST")
    manual = policy_for("MANUAL")

    assert isinstance(auto, DirectorAutonomyPolicy)
    assert auto.active_analysis is True
    assert auto.show_recommendations is True
    assert auto.auto_generate_proposals is True
    assert auto.advanced_default_visible is False

    assert assist.active_analysis is True
    assert assist.auto_generate_proposals is True

    assert manual.active_analysis is False
    assert manual.show_recommendations is False
    assert manual.auto_generate_proposals is False
    assert manual.advanced_default_visible is True


def test_runtime_and_model_selection_never_read_autonomy_policy() -> None:
    repo = Path(__file__).resolve().parents[3]
    runtime_paths = [
        repo / "backend" / "app" / "execution" / "product_path.py",
        repo / "backend" / "app" / "providers" / "selection.py",
        repo / "backend" / "app" / "execution" / "voice_path.py",
    ]
    for path in runtime_paths:
        source = path.read_text(encoding="utf-8")
        assert "autonomy_policy" not in source
        assert "director_autonomy" not in source


def _register_and_create_project(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"autonomy-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Autonomy",
        },
    )
    assert registered.status_code == 201, registered.text
    csrf = str(client.get("/api/v1/auth/csrf").json()["csrf_token"])
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Autonomy Project",
            "aspect_ratio": "9:16",
            "director_autonomy": "ASSIST",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"]), csrf


def test_patch_profile_switches_autonomy_with_version(client: TestClient) -> None:
    project_id, csrf = _register_and_create_project(client)
    updated = client.patch(
        f"/api/v1/projects/{project_id}/creative-profile",
        json={"expected_version": 1, "director_autonomy": "AUTO"},
        headers={CSRF_HEADER: csrf},
    )
    assert updated.status_code == 200, updated.text
    profile = updated.json()
    assert profile["director_autonomy"] == "AUTO"
    assert profile["version"] == 2


def test_patch_profile_stale_version_fails_closed(client: TestClient) -> None:
    project_id, csrf = _register_and_create_project(client)
    stale = client.patch(
        f"/api/v1/projects/{project_id}/creative-profile",
        json={"expected_version": 9, "director_autonomy": "MANUAL"},
        headers={CSRF_HEADER: csrf},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"
