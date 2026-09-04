"""WF13-01 — dispatch-time multi-subject fail-closed gate (G-WF-05/G-WF-06).

The planning surfaces assess capability, but only the reference compiler is
authoritative: when a shot's frozen participation plan carries more visible
controlled subjects than the resolved model's catalog manifest can bind as
reference images, the keyframe must not be submitted.  A silent single-reference
POST proves only character A survived, which is the banned outcome these tests
lock closed.
"""

from __future__ import annotations

from uuid import uuid4

from app.director.workflows.reference_capability import (
    MultiCharacterCapabilityStatus,
    dispatch_capability_gate,
    max_subject_references_from_catalog_manifest,
    visible_subject_count_from_snapshot,
)
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.manifest import ModelCapabilityManifest


def _agnes_operations() -> dict[str, object]:
    for m in seed_manifests_for(provider_type="agnes"):
        if m.get("media_kind") == "image":
            manifest = ModelCapabilityManifest.model_validate(m)
            return manifest.operations
    raise AssertionError("no Agnes image manifest seeded")


def _ent(screen_role: str) -> dict[str, object]:
    return {
        "asset_id": str(uuid4()),
        "asset_version_id": str(uuid4()),
        "screen_role": screen_role,
    }


def test_agnes_image_manifest_caps_reference_image_at_one() -> None:
    operations = _agnes_operations()
    assert max_subject_references_from_catalog_manifest(operations) == 1


def test_two_visible_subjects_fails_closed() -> None:
    operations = _agnes_operations()
    snapshot = {
        "workflow_participations": [_ent("primary"), _ent("secondary")],
    }
    gate = dispatch_capability_gate(snapshot=snapshot, operations=operations)
    assert gate is not None
    assert gate.status is MultiCharacterCapabilityStatus.UNSUPPORTED
    assert gate.required_subject_references == 2
    assert gate.max_subject_references == 1


def test_single_visible_subject_not_gated() -> None:
    operations = _agnes_operations()
    snapshot = {"workflow_participations": [_ent("primary")]}
    assert dispatch_capability_gate(snapshot=snapshot, operations=operations) is None


def test_no_plan_not_gated() -> None:
    operations = _agnes_operations()
    assert dispatch_capability_gate(snapshot={}, operations=operations) is None


def test_offscreen_subjects_do_not_count() -> None:
    operations = _agnes_operations()
    snapshot = {
        "workflow_participations": [_ent("primary"), _ent("offscreen")],
    }
    gate = dispatch_capability_gate(snapshot=snapshot, operations=operations)
    assert gate is None


def test_visible_subject_count_ignores_malformed_snapshot() -> None:
    assert visible_subject_count_from_snapshot({}) == 0
    assert visible_subject_count_from_snapshot({"workflow_participations": "nope"}) == 0
    assert (
        visible_subject_count_from_snapshot(
            {"workflow_participations": [{"screen_role": "primary"}]}
        )
        == 1
    )


def test_catalog_manifest_without_image_operation_fails_closed() -> None:
    assert max_subject_references_from_catalog_manifest({}) == 0
    assert max_subject_references_from_catalog_manifest(
        {"video.generate": {}}
    ) == 0


def test_approximate_only_via_explicit_registered_strategy() -> None:
    operations = _agnes_operations()
    snapshot = {
        "workflow_participations": [_ent("primary"), _ent("secondary")],
    }
    # Not accepted -> still UNSUPPORTED (no hidden fallback).
    gate = dispatch_capability_gate(
        snapshot=snapshot,
        operations=operations,
        accept_approximations=True,
        staged_strategy_id="not-a-registered-strategy",
    )
    assert gate is not None
    assert gate.status is MultiCharacterCapabilityStatus.UNSUPPORTED

    accepted = dispatch_capability_gate(
        snapshot=snapshot,
        operations=operations,
        accept_approximations=True,
        staged_strategy_id="two-pass-i2i-stabilize-v1",
    )
    assert accepted is not None
    assert accepted.status is MultiCharacterCapabilityStatus.APPROXIMATE
    assert accepted.approximate_strategy_id == "two-pass-i2i-stabilize-v1"
