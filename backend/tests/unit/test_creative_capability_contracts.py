"""CC1 + CC2 — creative capability contracts and registry."""

from __future__ import annotations

import pytest
from app.director.creative_capabilities.contracts import (
    ContentStage,
    CreativeInputField,
    CreativeOutputField,
    CreativeSkillResolution,
    CreativeSkillSpec,
    CreativeSkillStack,
    SkillCategory,
    contract_hash,
)
from app.director.creative_capabilities.registry import (
    CreativeSkillRegistry,
    build_skill_registry,
)
from pydantic import ValidationError


def _skill(key: str = "suspense-reversal-v1", version: str = "1.0.0") -> CreativeSkillSpec:
    return CreativeSkillSpec(
        skill_key=key,
        skill_version=version,
        display_name="Suspense Reversal",
        category=SkillCategory.STORY,
        description="Build tension then invert the audience expectation.",
        applicable_stages=[ContentStage.STORYBOARD],
        intent_tags=["suspense", "reversal"],
        required_context=["pov_character"],
        conflicts_with=["comedy-pacing-v1"],
        compatible_with=["character-consistency-v1"],
        input_contract=[
            CreativeInputField(field="pov_character", description="Who perceives", required=True)
        ],
        output_contract=[
            CreativeOutputField(
                field="turn_beat", description="Where the inversion lands", kind="beat"
            )
        ],
        strategy="frame a stable expectation, then invert at the act turn",
        quality_hints=["no early reveal", "keep the reversal motivated"],
    )


def test_skill_contract_is_frozen_and_forbid_extra() -> None:
    spec = _skill()
    with pytest.raises(ValidationError):
        CreativeSkillSpec.model_validate({**spec.model_dump(), "surprise": 1})


def test_contract_hash_is_semantic_and_deterministic() -> None:
    a = _skill()
    b = _skill()
    assert a.contract_hash == b.contract_hash
    assert a.contract_hash == contract_hash(a)
    # A semantic change changes the hash.
    c = _skill()
    changed = CreativeSkillSpec.model_validate({**c.model_dump(), "description": "different"})
    assert changed.contract_hash != a.contract_hash
    # The hash must be a bounded hex string (no nested object / non-json value).
    assert len(a.contract_hash) == 64
    assert a.contract_hash == a.contract_hash


def test_identity_and_conflict_detection() -> None:
    a = _skill()
    other = _skill(key="comedy-pacing-v1")
    assert a.identity == "suspense-reversal-v1@1.0.0"
    assert a.conflicts(other)
    assert a.conflicts(_skill(key="comedy-pacing-v1", version="2.0.0"))


def test_registry_register_get_list_versioned() -> None:
    spec = _skill()
    registry = build_skill_registry([spec])
    assert registry.contains("suspense-reversal-v1")
    assert registry.get("suspense-reversal-v1") is spec
    assert registry.get_versioned("suspense-reversal-v1", "1.0.0") is spec
    assert registry.all() == [spec]


def test_registry_keeps_highest_version() -> None:
    registry = CreativeSkillRegistry()
    v1 = _skill(version="1.0.0")
    v2 = _skill(version="2.0.0")
    registry.register(v1)
    registry.register(v2)
    assert registry.get("suspense-reversal-v1") is v2


def test_registry_idempotent_re_register_same_contract() -> None:
    registry = CreativeSkillRegistry()
    registry.register(_skill())
    # Re-registering the identical contract is idempotent.
    registry.register(_skill())
    assert registry.get("suspense-reversal-v1").contract_hash == _skill().contract_hash


def test_registry_refuses_same_version_new_contract() -> None:
    registry = CreativeSkillRegistry()
    registry.register(_skill())
    altered = CreativeSkillSpec.model_validate({**_skill().model_dump(), "strategy": "other"})
    with pytest.raises(ValueError, match="contract mismatch"):
        registry.register(altered)


def test_resolution_fails_closed_on_missing() -> None:
    registry = CreativeSkillRegistry()
    registry.register(_skill())
    ok = registry.resolve("suspense-reversal-v1")
    assert ok.status == "RESOLVED"
    assert ok.resolved_skill_key == "suspense-reversal-v1"
    assert ok.contract_hash is not None
    missing = registry.resolve("never-seen-v1")
    assert missing.status == "UNAVAILABLE"
    assert missing.resolved_skill_key is None


def test_skill_stack_tracks_selections() -> None:
    stack = CreativeSkillStack(selections=[_skill(), _skill(key="character-consistency-v1")])
    assert stack.keys() == ["suspense-reversal-v1", "character-consistency-v1"]
    assert stack.source == "explicit"


def test_resolution_model_shape() -> None:
    r = CreativeSkillResolution(
        requested_skill_key="k",
        resolved_skill_key="k",
        status="RESOLVED",
        contract_hash="a" * 64,
    )
    assert r.contract_hash == "a" * 64
