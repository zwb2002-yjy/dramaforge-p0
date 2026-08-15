"""Director budget counts and advisory identity evidence contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project
from app.director.models import BudgetAuthorization
from app.director.production_service import DirectorProductionService
from app.director.production_templates import dialogue_post_dub_definition
from app.director.quality_service import _identity_evidence_status
from app.director.shooting import (
    CostEstimatePayload,
    SelectedModelPlan,
    SelectionPlanPayload,
    StoryboardPlanPayload,
)
from app.director.shooting_service import DirectorShootingService
from app.shared.errors import ValidationAppError


def _storyboard() -> StoryboardPlanPayload:
    return StoryboardPlanPayload.model_validate(
        {
            "aspect_ratio": "9:16",
            "target_duration_seconds": 15,
            "shots": [
                {
                    "shot_id": "shot-1",
                    "shot_number": 1,
                    "duration_seconds": 5,
                    "location": "room",
                    "time_of_day": "night",
                    "shot_type": "medium",
                    "camera_move": "static",
                    "characters": ["Lin"],
                    "action": "Lin waits.",
                    "dialogue": [],
                    "image_prompt": "Lin waits",
                    "video_prompt": "Lin waits",
                    "transition": "cut",
                },
                {
                    "shot_id": "shot-2",
                    "shot_number": 2,
                    "duration_seconds": 5,
                    "location": "room",
                    "time_of_day": "night",
                    "shot_type": "over_shoulder",
                    "camera_move": "static",
                    "characters": ["Lin", "Ye"],
                    "action": "They face each other.",
                    "dialogue": [],
                    "image_prompt": "Lin and Ye",
                    "video_prompt": "Lin and Ye",
                    "transition": "cut",
                },
                {
                    "shot_id": "shot-3",
                    "shot_number": 3,
                    "duration_seconds": 5,
                    "location": "room",
                    "time_of_day": "night",
                    "shot_type": "close",
                    "camera_move": "static",
                    "characters": ["Ye"],
                    "action": "Ye answers.",
                    "dialogue": [],
                    "image_prompt": "Ye answers",
                    "video_prompt": "Ye answers",
                    "transition": "cut",
                },
            ],
        }
    )


def _selection() -> SelectionPlanPayload:
    plans = [
        SelectedModelPlan(
            purpose=purpose,
            model_binding_id=uuid4(),
            provider_type="fake",
            protocol_profile="fake-v1",
            model_id=f"fake-{purpose}",
            invoke_model_value=f"fake-{purpose}",
            manifest_hash="a" * 64,
            pricing_snapshot={"unit_amount": "1", "currency": "CNY"},
            status="ready",
        )
        for purpose in ("character_reference", "keyframe", "video", "voice")
    ]
    return SelectionPlanPayload(status="ready", plans=plans)


def _project() -> Project:
    return Project(
        workspace_id=uuid4(),
        name="Budget contract",
        aspect_ratio="9:16",
        budget_limit=Decimal("100"),
        budget_currency="CNY",
    )


def _authorization(cost: CostEstimatePayload) -> BudgetAuthorization:
    return BudgetAuthorization(
        project_id=uuid4(),
        workflow_run_id=uuid4(),
        authorization_kind="production_budget",
        idempotency_key="budget-contract",
        pricing_snapshot_id=cost.pricing_snapshot_id,
        limit_amount=Decimal("100"),
        consumed_amount=Decimal("0"),
        currency=cost.currency,
        authorized_by=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_cost_estimate_counts_every_character_reference_call() -> None:
    storyboard = _storyboard()

    cost = DirectorShootingService._build_cost_estimate(
        project=_project(),
        storyboard=storyboard,
        selection=_selection(),
        representative_shot_id="shot-2",
    )

    trial = {line.purpose: line for line in cost.trial}
    production = {line.purpose: line for line in cost.production}
    assert trial["character_reference"].quantity == 2
    assert cost.trial_total == Decimal("5")
    assert production["character_reference"].quantity == 4
    assert cost.production_total == Decimal("13")


def test_materialization_rejects_legacy_under_count_before_media_queueing() -> None:
    storyboard = _storyboard()
    cost = DirectorShootingService._build_cost_estimate(
        project=_project(),
        storyboard=storyboard,
        selection=_selection(),
        representative_shot_id="shot-2",
    )
    raw = cost.model_dump(mode="json")
    raw["production"] = [
        line for line in raw["production"] if line["purpose"] != "character_reference"
    ]
    raw["production_total"] = "9"
    under_counted = CostEstimatePayload.model_validate(raw)

    with pytest.raises(ValidationAppError) as caught:
        DirectorProductionService._assert_frozen_cost_contract(
            cost=under_counted,
            selection=_selection(),
            storyboard=storyboard,
            representative_shot_id="shot-2",
            stage="production",
            authorization=_authorization(under_counted),
        )

    assert caught.value.details["code"] == "COST_OPERATION_COUNT_MISMATCH"


@pytest.mark.parametrize(
    "raw_status",
    ["blocked", "failed", "needs_human", "warning", "not_applicable"],
)
def test_automatic_identity_status_requires_human_review(raw_status: str) -> None:
    assert _identity_evidence_status(raw_status) == "needs_human"


def test_passing_identity_evidence_remains_passed() -> None:
    assert _identity_evidence_status("passed") == "passed"


def test_current_shot_template_excludes_legacy_face_gate() -> None:
    definition = dialogue_post_dub_definition(
        character_reference_keys=["character-lead"],
        primary_character_reference_key="character-lead",
        context={"logical_shot_id": "shot-1"},
    )
    nodes = {str(node["key"]): str(node["type"]) for node in definition["nodes"]}
    edges = {tuple(edge) for edge in definition["edges"]}

    assert "identity_review" in nodes
    assert "face_review" not in nodes
    assert ("keyframe", "identity_review") in edges
    assert ("keyframe", "video") in edges
    assert ("identity_review", "video") not in edges
