"""P4-01 WorkbenchExecutionPlan contract tests.

Covers: name isolation from runtime.ResolvedReference, plan input/output
contracts (ExecutionModelResolution + mode_id + revision identity +
TranslationReport), deterministic fingerprint + idempotent freeze, secret-free
JSON, reference/control classification and reference counts.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.production.execution_plan import (
    CapabilityGap,
    ControlTranslation,
    PlannedReference,
    WorkbenchExecutionPlan,
    fingerprint_plan,
)
from app.providers.capabilities import Capability
from app.providers.model_resolution import ExecutionModelResolution
from app.providers.runtime import ResolvedReference
from app.providers.translation import TranslationReport
from pydantic import ValidationError


def _resolved_model() -> ExecutionModelResolution:
    return ExecutionModelResolution(
        requested_model_id="agnes/agnes-video-v2.0",
        resolved_model_id="agnes/agnes-video-v2.0",
        source="project_profile",
        status="RESOLVED",
        provider_model_binding_id=uuid4(),
        provider_connection_id=uuid4(),
        provider_connection_revision_id=uuid4(),
        credential_revision_id=uuid4(),
        catalog_entry_id=uuid4(),
        model_revision="v1",
        manifest_hash="a" * 64,
        invoke_model_value="agnes-video-v2.0",
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        mode_id="explicit_binding",
        native_options={"seed": 7},
    )


def _base_plan(**overrides: object) -> WorkbenchExecutionPlan:
    kwargs: dict[str, object] = {
        "project_id": uuid4(),
        "shot_id": uuid4(),
        "stage": "video",
        "prompt": "character walks into frame",
        "semantic_intent": {"intent": "shot_video"},
        "mode_id": "explicit_binding",
        "resolved_model": _resolved_model(),
        "capability": Capability.VIDEO_IMAGE_TO_VIDEO,
    }
    kwargs.update(overrides)
    return WorkbenchExecutionPlan(**kwargs)  # type: ignore[arg-type]


def test_planned_reference_does_not_collide_with_runtime_resolved_reference() -> None:
    # 07 §16: plan-era ResolvedReference renamed to PlannedReference so it
    # cannot collide with app.providers.runtime.ResolvedReference.
    assert PlannedReference is not ResolvedReference
    plan_fields = PlannedReference.model_fields
    assert "content_bytes" not in plan_fields
    assert "content_url" not in plan_fields
    assert "delivery" in plan_fields


def test_plan_carries_resolution_mode_and_revision_identity() -> None:
    connection_revision_id = uuid4()
    credential_revision_id = uuid4()
    plan = _base_plan(
        connection_revision_id=connection_revision_id,
        credential_revision_id=credential_revision_id,
        translation_report=TranslationReport(
            requested_options={"seed": 7},
            effective_options={"seed": 7},
        ),
    )
    assert plan.resolved_model.status == "RESOLVED"
    assert plan.mode_id == "explicit_binding"
    assert plan.resolved_model.provider_connection_revision_id is not None
    assert plan.resolved_model.credential_revision_id is not None
    assert plan.connection_revision_id == connection_revision_id
    assert plan.credential_revision_id == credential_revision_id
    assert plan.translation_report is not None
    payload = plan.model_dump(mode="json")
    assert payload["mode_id"] == "explicit_binding"
    assert payload["resolved_model"]["status"] == "RESOLVED"


def test_fingerprint_is_deterministic_and_freeze_is_idempotent() -> None:
    plan = _base_plan()
    frozen = plan.freeze()
    assert frozen.plan_fingerprint is not None
    assert len(frozen.plan_fingerprint) == 64
    # idempotent: freezing an already-frozen plan keeps the fingerprint
    assert frozen.freeze().plan_fingerprint == frozen.plan_fingerprint
    # same canonical payload -> same fingerprint regardless of key order
    left = {"a": 1, "b": {"c": [1, 2]}}
    right = {"b": {"c": [1, 2]}, "a": 1}
    assert fingerprint_plan(left) == fingerprint_plan(right)
    # different payload -> different fingerprint
    assert fingerprint_plan({"a": 1}) != fingerprint_plan({"a": 2})


def test_plan_json_contains_no_secret_keys() -> None:
    plan = _base_plan().freeze()
    # Secret *values* must never appear. Identity UUIDs such as
    # credential_revision_id are references, not secrets (07 §16 requires them).
    forbidden = ("api_key", "apikey", "authorization", "ciphertext", "password", "bearer", "secret")

    def walk(value: object, path: str = "") -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(frag in normalized for frag in forbidden):
                    hits.append(f"{path}.{key}")
                hits.extend(walk(child, f"{path}.{key}"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                hits.extend(walk(child, f"{path}[{index}]"))
        return hits

    assert walk(plan.model_dump(mode="json")) == []


def test_reference_counts_classify_delivery() -> None:
    plan = _base_plan(
        planned_references=[
            PlannedReference(purpose="identity", artifact_id=uuid4(), delivery="exact"),
            PlannedReference(purpose="clothing", artifact_id=uuid4(), delivery="approximate"),
            PlannedReference(purpose="action", artifact_id=uuid4(), delivery="unsupported"),
            PlannedReference(purpose="style", artifact_id=uuid4(), delivery="exact"),
        ]
    )
    assert plan.reference_counts == {"exact": 2, "approximate": 1, "unsupported": 1}


def test_unsupported_control_surfaces_not_silently_dropped() -> None:
    plan = _base_plan(
        unsupported_controls=[
            ControlTranslation(
                control="camera_motion",
                option="camera_motion",
                status="unsupported",
                reason="manifest does not declare camera_motion",
            )
        ],
        capability_gaps=[
            CapabilityGap(
                capability=Capability.VIDEO_IMAGE_TO_VIDEO,
                controls=["camera_motion"],
                severity="fatal",
                reason="model cannot honor camera_motion",
            )
        ],
    )
    assert len(plan.unsupported_controls) == 1
    assert len(plan.capability_gaps) == 1
    assert plan.capability_gaps[0].severity == "fatal"
    # nothing silently dropped: the gap is observable in the JSON plan
    payload = plan.model_dump(mode="json")
    assert payload["capability_gaps"][0]["controls"] == ["camera_motion"]


def test_planned_reference_is_frozen() -> None:
    reference = PlannedReference(purpose="identity", artifact_id=uuid4())
    with pytest.raises(ValidationError):
        reference.delivery = "unsupported"  # type: ignore[misc]


def test_plan_requires_mode_and_capability() -> None:
    with pytest.raises(ValidationError):
        _base_plan(mode_id="", capability=Capability.VIDEO_IMAGE_TO_VIDEO)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _base_plan(mode_id="explicit_binding", capability="not-a-capability")  # type: ignore[arg-type]
