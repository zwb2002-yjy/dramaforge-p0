"""Shooting package contracts: locked inputs, no media calls and fail-closed preflight."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _setup_confirmed_story(client: TestClient) -> str:
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "shooting@example.com",
                "password": "password123",
                "display_name": "Creator",
            },
        ).status_code
        == 201
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    project = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Dialogue", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    project_id = str(project.json()["id"])
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/director/workflow",
            json={},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 201
    )
    story = {
        "selected_concept_id": "concept-1",
        "theme": "honesty",
        "core_conflict": "Lin Xia must decide whether to hear the truth before leaving",
        "emotional_direction": "restraint to honesty",
        "ending": "They do not reconcile immediately but finally state their choices",
        "characters": [
            {
                "name": "Lin Xia",
                "identity": "designer who plans to leave",
                "desire": "hear the real answer",
                "fear_or_cost": "admit that she has been waiting",
            },
            {
                "name": "Cheng Ye",
                "identity": "photographer who avoids difficult conversations",
                "desire": "tell the truth before it is too late",
                "fear_or_cost": "accept that honesty may not repair the relationship",
            },
        ],
    }
    script = {
        "title": "The last sentence",
        "target_duration_seconds": 24,
        "setup": "Lin Xia is at the doorway with her luggage.",
        "turn": "Cheng Ye admits that his earlier refusal was not his real decision.",
        "ending": story["ending"],
        "dialogue": [
            {"speaker": "Lin Xia", "text": "You are still late.", "emotion": "restrained"},
            {"speaker": "Cheng Ye", "text": "This time I will say it clearly.", "emotion": "firm"},
            {"speaker": "Lin Xia", "text": "Then finish it.", "emotion": "honest"},
        ],
    }
    for kind, payload in (
        ("story_core", story),
        ("episode_script", script),
        (
            "story_review",
            {
                "status": "passed",
                "logic_issues": [],
                "pacing_issues": [],
                "duration_risks": [],
                "closure_issues": [],
                "revision_suggestions": [],
            },
        ),
    ):
        response = client.post(
            f"/api/v1/projects/{project_id}/director/artifact-versions",
            json={"artifact_kind": kind, "payload": payload, "source_kind": "user"},
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 201, response.text
    approved = client.post(
        f"/api/v1/projects/{project_id}/director/approvals",
        json={"approval_kind": "creative_plan", "idempotency_key": "confirm-story"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert approved.status_code == 201, approved.text
    return project_id


def test_shooting_package_requires_text_authorization(client: TestClient) -> None:
    project_id = _setup_confirmed_story(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/director/shooting/package/generate",
        json={"authorize_text_calls": False, "idempotency_key": "shooting-no-auth"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 422
    assert response.json()["details"]["code"] == "TEXT_CALL_AUTHORIZATION_REQUIRED"


def test_shooting_package_is_versioned_and_does_not_start_media(client: TestClient) -> None:
    project_id = _setup_confirmed_story(client)
    body = {"authorize_text_calls": True, "idempotency_key": "shooting-v1"}
    response = client.post(
        f"/api/v1/projects/{project_id}/director/shooting/package/generate",
        json=body,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    package = response.json()
    assert package["visual_bible"]["payload"]["aspect_ratio"] == "16:9"
    assert len(package["storyboard_plan"]["payload"]["shots"]) == 4
    assert package["selection_plan"]["payload"]["status"] == "configuration_required"
    assert package["trial_plan"]["payload"]["budget_authorization_required"] is True

    repeated = client.post(
        f"/api/v1/projects/{project_id}/director/shooting/package/generate",
        json=body,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["storyboard_plan"]["id"] == package["storyboard_plan"]["id"]

    snapshot = client.get(f"/api/v1/projects/{project_id}/director/workflow").json()
    assert snapshot["status"] == "awaiting_shooting_confirmation"
    approved = client.post(
        f"/api/v1/projects/{project_id}/director/approvals",
        json={"approval_kind": "shooting_plan", "idempotency_key": "confirm-shooting"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["workflow"]["status"] == "awaiting_trial_authorization"

    production = client.get(f"/api/v1/projects/{project_id}/snapshot")
    assert production.status_code == 200, production.text
    assert production.json()["node_runs"] == []
    assert production.json()["artifacts"] == []


def test_manual_shooting_payload_rejects_real_person_and_voice_clone(
    client: TestClient,
) -> None:
    project_id = _setup_confirmed_story(client)
    rejected = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": "character_bible",
            "source_kind": "user",
            "payload": {
                "policy": "fictional_characters_only",
                "real_person_reference_allowed": True,
                "characters": [],
            },
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert rejected.status_code == 422
    assert rejected.json()["details"]["code"] == "SHOOTING_ARTIFACT_SCHEMA_INVALID"
