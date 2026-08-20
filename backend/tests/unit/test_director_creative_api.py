"""Creative-stage HTTP contracts for novice entry and ownership-preserving flow."""

from __future__ import annotations

import pytest
from app.creation.service import CreationService
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _setup(client: TestClient, email: str) -> str:
    assert client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": "Creator"},
    ).status_code == 201
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    project = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "My Story", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    project_id = str(project.json()["id"])
    started = client.post(
        f"/api/v1/projects/{project_id}/director/workflow",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert started.status_code == 201, started.text
    return project_id


def test_no_idea_preference_loop_and_creative_confirmation(client: TestClient) -> None:
    project_id = _setup(client, "creative@example.com")
    concept_request = {
        "entry_mode": "no_idea",
        "creation_goal": "balanced",
        "authorize_text_call": True,
        "idempotency_key": "concepts-v1",
    }
    concepts = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json=concept_request,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert concepts.status_code == 201, concepts.text
    concept_version = concepts.json()
    assert concept_version["artifact_kind"] == "concept_set"
    assert len(concept_version["payload"]["concepts"]) == 3
    assert concept_version["payload"]["creation_goal"] == "balanced"

    # Transport retries reuse the same WorkflowStepRun/output, not another paid call.
    repeated = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json=concept_request,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == concept_version["id"]

    preference = client.post(
        f"/api/v1/projects/{project_id}/director/creative/preferences/interpret",
        json={
            "source_concept_version_id": concept_version["id"],
            "feedback": "我喜欢真实情绪，不喜欢硬凑反转，也不要为了流量失去主题。",
            "authorize_text_call": True,
            "idempotency_key": "preference-v1",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert preference.status_code == 201, preference.text
    preference_version = preference.json()
    assert preference_version["artifact_kind"] == "preference_understanding"
    assert preference_version["payload"]["interpretation_summary"]

    revised = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            **concept_request,
            "idempotency_key": "concepts-v2",
            "confirmed_preference_version_id": preference_version["id"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["id"] != concept_version["id"]
    selected = revised.json()["payload"]["concepts"][0]

    package = client.post(
        f"/api/v1/projects/{project_id}/director/creative/package/generate",
        json={
            "concept_version_id": revised.json()["id"],
            "selected_concept_id": selected["concept_id"],
            "theme": "坦诚并不能消除代价，但能让选择属于自己",
            "core_conflict": "主角必须在离开前决定是否说出一直隐瞒的真相",
            "emotional_direction": "从克制、防备走向诚实但不煽情",
            "ending": "两人没有立刻和好，却第一次明确说出各自的选择",
            "authorize_text_call": True,
            "idempotency_key": "creative-package-v1",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert package.status_code == 201, package.text
    package_body = package.json()
    assert package_body["story_core"]["payload"]["theme"].startswith("坦诚并不能")
    assert 15 <= package_body["episode_script"]["payload"]["target_duration_seconds"] <= 30
    assert package_body["story_review"]["payload"]["status"] in {
        "passed",
        "needs_revision",
    }
    approval = client.post(
        f"/api/v1/projects/{project_id}/director/approvals",
        json={"approval_kind": "creative_plan", "idempotency_key": "creative-confirm"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert approval.status_code == 201, approval.text
    assert approval.json()["workflow"]["status"] == "drafting_shooting_plan"


def test_text_calls_require_explicit_authorization_and_script_rights(
    client: TestClient,
) -> None:
    project_id = _setup(client, "rights@example.com")
    unauthorized = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            "entry_mode": "one_sentence",
            "idea": "一个人错过最后一班车",
            "authorize_text_call": False,
            "idempotency_key": "no-auth",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert unauthorized.status_code == 422
    assert unauthorized.json()["details"]["code"] == "TEXT_CALL_AUTHORIZATION_REQUIRED"

    no_rights = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            "entry_mode": "import_script",
            "script_text": "这是一个待改编剧本。",
            "adaptation_mode": "faithful",
            "source_rights_confirmed": False,
            "authorize_text_call": True,
            "idempotency_key": "no-rights",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert no_rights.status_code == 422


def test_story_review_can_be_regenerated_without_rewriting_creative_facts(
    client: TestClient,
) -> None:
    project_id = _setup(client, "review-recovery@example.com")
    story = {
        "selected_concept_id": "elevator-growth",
        "theme": "直面过去",
        "core_conflict": "林晚必须决定是否继续逃避。",
        "emotional_direction": "不安到坚定",
        "ending": "林晚迈出电梯，未来的自己肯定了她的勇气。",
        "characters": [
            {
                "name": "林晚",
                "identity": "独自乘坐电梯的成年女性",
                "desire": "摆脱过去的阴影",
                "fear_or_cost": "再次经历痛苦",
            }
        ],
    }
    script = {
        "title": "十三楼",
        "target_duration_seconds": 15,
        "setup": "林晚独自在电梯里。",
        "turn": "她决定不再逃避。",
        "ending": "林晚迈出电梯，未来的自己肯定了她的勇气。",
        "dialogue": [
            {"speaker": "林晚", "text": "我不再逃了。", "emotion": "坚定"},
            {"speaker": "林晚", "text": "你更勇敢。", "emotion": "温柔"},
        ],
    }
    for kind, payload in (("story_core", story), ("episode_script", script)):
        response = client.post(
            f"/api/v1/projects/{project_id}/director/artifact-versions",
            json={"artifact_kind": kind, "payload": payload, "source_kind": "user"},
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 201, response.text

    body = {"idempotency_key": "review-current-creative"}
    review = client.post(
        f"/api/v1/projects/{project_id}/director/creative/review/generate",
        json=body,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert review.status_code == 201, review.text
    assert review.json()["artifact_kind"] == "story_review"
    assert review.json()["payload"]["status"] == "passed"

    repeated = client.post(
        f"/api/v1/projects/{project_id}/director/creative/review/generate",
        json=body,
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == review.json()["id"]


def test_director_does_not_repost_provider_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _setup(client, "provider-failure@example.com")
    calls = 0

    async def fail_provider_call(
        *args: object, **kwargs: object
    ) -> tuple[object, str, str, dict[str, object]]:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider rate limited")

    monkeypatch.setattr(CreationService, "_run_text_llm_attempt", fail_provider_call)
    response = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            "entry_mode": "no_idea",
            "creation_goal": "balanced",
            "authorize_text_call": True,
            "idempotency_key": "provider-failure",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "DIRECTOR_SKILL_FAILED"
    assert calls == 1


def test_selected_concept_must_come_from_exact_version(client: TestClient) -> None:
    project_id = _setup(client, "selected@example.com")
    concepts = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            "entry_mode": "one_sentence",
            "idea": "两个陌生人在电梯停电时交换秘密",
            "authorize_text_call": True,
            "idempotency_key": "concepts",
        },
        headers={CSRF_HEADER: _csrf(client)},
    ).json()
    invalid = client.post(
        f"/api/v1/projects/{project_id}/director/creative/package/generate",
        json={
            "concept_version_id": concepts["id"],
            "selected_concept_id": "made-up-concept",
            "theme": "信任",
            "core_conflict": "两人必须决定是否相信彼此",
            "emotional_direction": "紧张到释然",
            "ending": "门打开后他们选择继续交谈",
            "authorize_text_call": True,
            "idempotency_key": "invalid-selection",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "selected_concept_id is not in the concept version"
