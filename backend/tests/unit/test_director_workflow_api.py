"""Contract tests for the controlled Director workflow core."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project(client: TestClient, email: str = "director@example.com") -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": "Director"},
    )
    assert registered.status_code == 201, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "First Film",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _start(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/director/workflow",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _artifact(
    client: TestClient,
    project_id: str,
    kind: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    defaults: dict[str, dict[str, object]] = {
        "story_core": {
            "selected_concept_id": "concept-1",
            "theme": "勇气",
            "core_conflict": "主角必须决定是否说出真相",
            "emotional_direction": "克制到坦诚",
            "ending": "主角承担代价并说出真相",
            "characters": [
                {
                    "name": "林夏",
                    "identity": "准备离开的设计师",
                    "desire": "得到真实答案",
                    "fear_or_cost": "承认自己一直在等待",
                }
            ],
        },
        "episode_script": {
            "title": "最后一句",
            "target_duration_seconds": 20,
            "setup": "林夏准备离开。",
            "turn": "对方终于说出真相。",
            "ending": "林夏决定听完再走。",
            "dialogue": [{"speaker": "林夏", "text": "你还有一句话。", "emotion": "克制"}],
        },
        "story_review": {
            "status": "passed",
            "logic_issues": [],
            "pacing_issues": [],
            "duration_risks": [],
            "closure_issues": [],
            "revision_suggestions": [],
        },
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": kind,
            "payload": payload or defaults.get(kind, {"kind": kind}),
            "source_kind": "user",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve(
    client: TestClient,
    project_id: str,
    kind: str,
    key: str,
    authorization_id: str | None = None,
) -> object:
    return client.post(
        f"/api/v1/projects/{project_id}/director/approvals",
        json={
            "approval_kind": kind,
            "idempotency_key": key,
            "budget_authorization_id": authorization_id,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )


def test_template_registry_and_workflow_start_are_deterministic(client: TestClient) -> None:
    project_id = _project(client)
    first = _start(client, project_id)
    second = _start(client, project_id)
    assert first["id"] == second["id"]
    assert first["template_id"] == "live_action_dialogue_short"
    assert first["template_version"] == "1.0.0"
    assert first["status"] == "drafting_creative"


def test_creative_confirmation_requires_complete_versioned_inputs(
    client: TestClient,
) -> None:
    project_id = _project(client, "inputs@example.com")
    _start(client, project_id)
    _artifact(client, project_id, "episode_script")
    incomplete = _approve(client, project_id, "creative_plan", "creative-1")
    assert incomplete.status_code == 422
    assert incomplete.json()["details"]["code"] == "APPROVAL_INPUTS_INCOMPLETE"
    assert incomplete.json()["details"]["missing_artifact_kinds"] == [
        "story_core",
        "story_review",
    ]


def test_four_stage_order_locks_inputs_and_budget_requires_explicit_authorization(
    client: TestClient,
) -> None:
    project_id = _project(client, "ordered@example.com")
    _start(client, project_id)
    for kind in ("story_core", "episode_script", "story_review"):
        _artifact(client, project_id, kind)
    creative = _approve(client, project_id, "creative_plan", "creative-confirm")
    assert creative.status_code == 201, creative.text
    assert creative.json()["workflow"]["status"] == "drafting_shooting_plan"
    assert set(creative.json()["approval"]["approved_artifact_versions"]) == {
        "story_core",
        "episode_script",
        "story_review",
    }
    direct_locked_edit = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": "story_core",
            "payload": {"theme": "bypass"},
            "source_kind": "user",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert direct_locked_edit.status_code == 422
    assert direct_locked_edit.json()["details"]["code"] == "ARTIFACT_STAGE_NOT_ALLOWED"

    shooting_package = client.post(
        f"/api/v1/projects/{project_id}/director/shooting/package/generate",
        json={"authorize_text_calls": True, "idempotency_key": "ordered-shooting"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert shooting_package.status_code == 201, shooting_package.text
    shooting = _approve(client, project_id, "shooting_plan", "shooting-confirm")
    assert shooting.status_code == 201, shooting.text
    assert shooting.json()["workflow"]["status"] == "awaiting_trial_authorization"

    no_budget = _approve(client, project_id, "trial_budget", "trial-no-budget")
    assert no_budget.status_code == 422
    assert no_budget.json()["detail"] == "budget authorization is required"

    authorization = client.post(
        f"/api/v1/projects/{project_id}/director/budget-authorizations",
        json={
            "authorization_kind": "trial_budget",
            "idempotency_key": "trial-budget-1",
            "pricing_snapshot_id": "price-v1",
            "limit_amount": "5.50",
            "currency": "CNY",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert authorization.status_code == 201, authorization.text
    approved = _approve(
        client,
        project_id,
        "trial_budget",
        "trial-approved",
        str(authorization.json()["id"]),
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["workflow"]["status"] == "trial_running"

    # Media production is no longer forgeable by publishing a trial_review.
    # The real path is materialize -> inspect evidence -> creator review.
    forged_review = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": "trial_review",
            "payload": {"accepted_quality": True, "evidence_refs": ["artifact:test"]},
            "source_kind": "user",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert forged_review.status_code == 422


def test_natural_language_change_never_applies_before_confirmation(
    client: TestClient,
) -> None:
    project_id = _project(client, "change@example.com")
    _start(client, project_id)
    original = _artifact(
        client,
        project_id,
        "story_core",
        {
            "selected_concept_id": "concept-1",
            "theme": "勇气",
            "core_conflict": "主角必须决定是否承担真相的代价",
            "emotional_direction": "犹豫到坚定",
            "ending": "happy",
            "characters": [
                {
                    "name": "林夏",
                    "identity": "准备离开的设计师",
                    "desire": "说出真相",
                    "fear_or_cost": "可能失去对方",
                }
            ],
        },
    )
    _artifact(client, project_id, "episode_script")
    _artifact(client, project_id, "story_review")
    proposal = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals",
        json={
            "idempotency_key": "change-ending-1",
            "target_artifact_kind": "story_core",
            "summary": "把结局改成开放式",
            "replacement_payload": {
                "selected_concept_id": "concept-1",
                "theme": "勇气",
                "core_conflict": "主角必须决定是否承担真相的代价",
                "emotional_direction": "犹豫到坚定",
                "ending": "open",
                "characters": [
                    {
                        "name": "林夏",
                        "identity": "准备离开的设计师",
                        "desire": "说出真相",
                        "fear_or_cost": "可能失去对方",
                    }
                ],
            },
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert proposal.status_code == 201, proposal.text
    body = proposal.json()
    assert body["proposal"]["status"] == "awaiting_confirmation"
    snapshot = client.get(f"/api/v1/projects/{project_id}/director/workflow")
    assert body["impact"]["invalidated_version_ids"] == [
        original["id"],
        snapshot.json()["current_artifact_versions"]["episode_script"],
        snapshot.json()["current_artifact_versions"]["story_review"],
    ]
    assert snapshot.json()["current_artifact_versions"]["story_core"] == original["id"]

    applied = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals/{body['proposal']['id']}/confirm",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["id"] != original["id"]
    assert applied.json()["payload"]["ending"] == "open"
    changed_snapshot = client.get(f"/api/v1/projects/{project_id}/director/workflow").json()
    assert changed_snapshot["current_artifact_versions"] == {"story_core": applied.json()["id"]}


def test_change_proposal_requires_current_artifact_and_confirmation_state(
    client: TestClient,
) -> None:
    project_id = _project(client, "change-state@example.com")
    _start(client, project_id)
    rejected = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals",
        json={
            "idempotency_key": "change-too-early",
            "target_artifact_kind": "story_core",
            "summary": "提前修改",
            "replacement_payload": {},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert rejected.status_code == 422
    assert rejected.json()["details"]["code"] == "CHANGE_PROPOSAL_NOT_ALLOWED"

    for kind in ("story_core", "episode_script", "story_review"):
        _artifact(client, project_id, kind)
    missing = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals",
        json={
            "idempotency_key": "change-missing-target",
            "target_artifact_kind": "storyboard_plan",
            "summary": "没有当前版本",
            "replacement_payload": {},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert missing.status_code == 422
    assert missing.json()["details"]["code"] == "CHANGE_TARGET_NOT_CURRENT"


def test_pending_change_blocks_stage_approval_until_confirmed(client: TestClient) -> None:
    project_id = _project(client, "change-approval@example.com")
    _start(client, project_id)
    original = _artifact(client, project_id, "story_core")
    _artifact(client, project_id, "episode_script")
    _artifact(client, project_id, "story_review")
    proposal = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals",
        json={
            "idempotency_key": "change-before-approval",
            "target_artifact_kind": "story_core",
            "summary": "调整结局",
            "replacement_payload": {
                **original["payload"],
                "ending": "主角选择留下来面对真相",
            },
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert proposal.status_code == 201, proposal.text
    blocked = _approve(client, project_id, "creative_plan", "approval-with-pending-change")
    assert blocked.status_code == 422
    assert blocked.json()["details"]["code"] == "PENDING_CHANGE_REQUIRES_CONFIRMATION"
    blocked_write = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": "episode_script",
            "payload": {
                "title": "不会写入",
                "target_duration_seconds": 20,
                "setup": "开始",
                "turn": "转折",
                "ending": "结局",
                "dialogue": [{"speaker": "林夏", "text": "等一下。", "emotion": "克制"}],
            },
            "source_kind": "user",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert blocked_write.status_code == 422
    assert blocked_write.json()["details"]["code"] == "PENDING_CHANGE_REQUIRES_CONFIRMATION"


def test_locked_creative_change_is_available_after_creative_approval(
    client: TestClient,
) -> None:
    project_id = _project(client, "locked-change@example.com")
    _start(client, project_id)
    original = _artifact(client, project_id, "story_core")
    _artifact(client, project_id, "episode_script")
    _artifact(client, project_id, "story_review")
    approved = _approve(client, project_id, "creative_plan", "lock-creative-plan")
    assert approved.status_code == 201, approved.text
    assert approved.json()["workflow"]["status"] == "drafting_shooting_plan"

    proposal = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals",
        json={
            "idempotency_key": "locked-story-change",
            "target_artifact_kind": "story_core",
            "summary": "调整已锁定结局",
            "replacement_payload": {
                **original["payload"],
                "ending": "主角留下来面对真相",
            },
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert proposal.status_code == 201, proposal.text
    proposal_body = proposal.json()
    assert proposal_body["proposal"]["base_version_id"] == original["id"]

    workspace = client.get(
        f"/api/v1/projects/{project_id}/director/workspace-snapshot"
    ).json()
    assert workspace["current_artifacts"]["story_core"]["status"] == "locked"
    assert workspace["allowed_actions"] == ["confirm_change"]

    applied = client.post(
        f"/api/v1/projects/{project_id}/director/change-proposals/"
        f"{proposal_body['proposal']['id']}/confirm",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert applied.status_code == 200, applied.text
    changed_workspace = client.get(
        f"/api/v1/projects/{project_id}/director/workspace-snapshot"
    ).json()
    assert changed_workspace["workflow"]["status"] == "awaiting_creative_confirmation"
    assert changed_workspace["workflow"]["current_artifact_versions"] == {
        "story_core": applied.json()["id"]
    }
    assert changed_workspace["approvals"][0]["invalidated_at"] is not None


def test_browser_cannot_forge_agent_artifact_source(client: TestClient) -> None:
    project_id = _project(client, "source@example.com")
    _start(client, project_id)
    forged = client.post(
        f"/api/v1/projects/{project_id}/director/artifact-versions",
        json={
            "artifact_kind": "story_core",
            "payload": {"theme": "x"},
            "source_kind": "agent",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert forged.status_code == 422


def test_trial_materialization_fails_closed_when_models_are_not_ready(
    client: TestClient,
) -> None:
    project_id = _project(client, "trial-blocked@example.com")
    _start(client, project_id)
    for kind in ("story_core", "episode_script", "story_review"):
        _artifact(client, project_id, kind)
    assert _approve(client, project_id, "creative_plan", "blocked-creative").status_code == 201
    package = client.post(
        f"/api/v1/projects/{project_id}/director/shooting/package/generate",
        json={"authorize_text_calls": True, "idempotency_key": "blocked-shooting"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert package.status_code == 201, package.text
    assert _approve(client, project_id, "shooting_plan", "blocked-shooting-ok").status_code == 201
    authorization = client.post(
        f"/api/v1/projects/{project_id}/director/budget-authorizations",
        json={
            "authorization_kind": "trial_budget",
            "idempotency_key": "blocked-trial-budget",
            "pricing_snapshot_id": "provider-price-unknown",
            "limit_amount": "5.50",
            "currency": "CNY",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    approved = _approve(
        client,
        project_id,
        "trial_budget",
        "blocked-trial-approved",
        str(authorization.json()["id"]),
    )
    assert approved.status_code == 201, approved.text
    materialize = client.post(
        f"/api/v1/projects/{project_id}/director/trial/materialize",
        json={"idempotency_key": "blocked-trial-materialize"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert materialize.status_code == 422, materialize.text
    assert materialize.json()["details"]["code"] == "MEDIA_SELECTION_NOT_READY"
    production = client.get(f"/api/v1/projects/{project_id}/snapshot").json()
    assert production["node_runs"] == []
    assert production["artifacts"] == []
