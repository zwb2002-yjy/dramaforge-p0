"""CC7 + CC8 — shot language packs and quality policy registry."""

from __future__ import annotations

import pytest
from app.director.creative_capabilities.pack_registry import PackRegistry
from app.director.creative_capabilities.shot_language import (
    QualityDimensionKind,
    QualityPolicySpec,
)
from app.director.creative_capabilities.shot_language_compiler import ShotLanguageCompiler
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)


def test_six_shot_language_packs_structured() -> None:
    assert len(SHOT_LANGUAGE_PACKS) == 6
    keys = {p.pack_key for p in SHOT_LANGUAGE_PACKS}
    assert len(keys) == 6
    for pack in SHOT_LANGUAGE_PACKS:
        assert pack.preferred_shot_sizes
        assert pack.camera_angles
        assert pack.camera_motion
        assert pack.contract_hash


def test_shot_language_compiler_emits_patch() -> None:
    pack = next(p for p in SHOT_LANGUAGE_PACKS if p.pack_key == "dialogue_classic_coverage_v1")
    patch = ShotLanguageCompiler().compile(pack=pack)
    assert patch.pack_key == "dialogue_classic_coverage_v1"
    assert patch.shot_size == "medium"
    assert patch.camera_angle == "eye_level"
    assert patch.cutting_rule is not None
    assert patch.provenance == "shot-language-pack"


def test_shot_language_patch_is_frozen_and_forbid() -> None:
    from app.director.creative_capabilities.shot_language import ShotDirectorIntentPatch
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ShotDirectorIntentPatch(pack_key="x", pack_version="1", extra="nope")


def test_five_quality_policies() -> None:
    assert len(QUALITY_POLICIES) == 5
    policy_keys = {p.policy_key for p in QUALITY_POLICIES}
    assert len(policy_keys) == 5
    for policy in QUALITY_POLICIES:
        assert policy.contract_hash


def test_quality_policy_distinguishes_blocker_warning_human() -> None:
    mq = next(p for p in QUALITY_POLICIES if p.policy_key == "multi_character_quality_v1")
    kinds = {d.kind for d in mq.dimensions}
    assert QualityDimensionKind.TECHNICAL_BLOCKER in kinds
    # Not everything is a hard blocker: subjective aesthetics stay human.
    assert QualityDimensionKind.HUMAN_JUDGMENT in kinds
    assert mq.hard_blockers
    assert mq.human_review_dimensions
    assert mq.warning_thresholds


def test_quality_policy_registry() -> None:
    registry = PackRegistry(key_field="policy_key")
    for policy in QUALITY_POLICIES:
        registry.register(policy)
    assert registry.contains("dialogue_identity_quality_v1")
    assert registry.get("dialogue_identity_quality_v1") is not None
    assert len(registry.all()) == 5
    # Idempotent re-register same contract.
    registry.register(QUALITY_POLICIES[0])


def test_quality_policy_refuses_contract_overwrite() -> None:
    registry = PackRegistry(key_field="policy_key")
    registry.register(QUALITY_POLICIES[0])

    changed = QUALITY_POLICIES[0].model_copy(deep=True)
    altered = QualityPolicySpec.model_validate(
        {**changed.model_dump(), "description": "different description"}
    )
    with pytest.raises(ValueError, match="contract mismatch"):
        registry.register(altered)


def test_human_dimensions_never_auto_block() -> None:
    # G-CC-02: subjective aesthetics must not become a deterministic blocker.
    for policy in QUALITY_POLICIES:
        human_keys = {d.key for d in policy.human_review_dimensions}
        blocker_keys = {d.key for d in policy.hard_blockers}
        assert not (human_keys & blocker_keys), f"{policy.policy_key} double-classifies"
