"""CC3 + CC4 — skill composition engine and baseline skill library."""

from __future__ import annotations

from app.director.creative_capabilities.composer import (
    CreativeSkillComposer,
    MergePolicy,
    ResolutionStatus,
)
from app.director.creative_capabilities.contracts import (
    ContentStage,
    CreativeSkillSpec,
    SkillCategory,
)
from app.director.creative_capabilities.registry import build_skill_registry
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS

SKILLS = build_skill_registry(BASELINE_SKILLS)


def _key(spec: CreativeSkillSpec) -> str:
    return spec.skill_key


def test_library_seeds_ten_distinct_skills() -> None:
    assert len(BASELINE_SKILLS) == 10
    keys = [_key(s) for s in BASELINE_SKILLS]
    assert len(set(keys)) == 10
    for skill in BASELINE_SKILLS:
        assert skill.contract_hash
        assert skill.strategy
        assert skill.category.value


def test_skills_have_distinct_structural_contracts_not_just_names() -> None:
    # No two skills share the same strategy signature (the composition essence).
    strategies = {skill.strategy for skill in BASELINE_SKILLS}
    assert len(strategies) == 10
    # Distinct output fields per skill (structural identity, not a copy).
    output_signatures = {
        tuple(sorted(f.field for f in skill.output_contract)) for skill in BASELINE_SKILLS
    }
    assert len(output_signatures) == 10


def test_every_skill_registers_and_resolves() -> None:
    for skill in BASELINE_SKILLS:
        resolution = SKILLS.resolve(skill.skill_key)
        assert resolution.status == "RESOLVED"
        assert resolution.contract_hash == skill.contract_hash


def test_every_skill_unavailable_key_fails_closed() -> None:
    resolution = SKILLS.resolve("not-a-real-skill-v9")
    assert resolution.status == "UNAVAILABLE"
    assert resolution.resolved_skill_key is None


def test_composer_orders_and_tracks_provenance() -> None:
    stacked = [SKILLS.get("suspense-reversal-v1"), SKILLS.get("continuity-guardian-v1")]
    composer = CreativeSkillComposer()
    resolution = composer.compose(skills=stacked)  # type: ignore[list-item]
    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.keys == ["suspense-reversal-v1", "continuity-guardian-v1"]
    assert all(entry.source == "explicit" for entry in resolution.entries)
    assert resolution.stack.source == "explicit"


def test_composer_surfaces_conflict_not_silent_drop() -> None:
    # suspense-reversal-v1 conflicts with linear-reveal-v1 (by contract).
    linear = _make_conflicting("linear-reveal-v1", "suspense-reversal-v1")
    stacked = [SKILLS.get("suspense-reversal-v1"), linear]
    composer = CreativeSkillComposer()
    resolution = composer.compose(skills=stacked)  # type: ignore[list-item]
    assert resolution.status is ResolutionStatus.CONFLICT
    assert resolution.conflicts
    # Both sides are still recorded — nothing silently removed (G-CC-01).
    assert len(resolution.keys) == 2
    conflict_entry = next(e for e in resolution.entries if e.spec.skill_key == "linear-reveal-v1")
    assert conflict_entry.merge_policy is MergePolicy.CONFLICT


def test_composer_honors_stage_scope() -> None:
    # short-drama-hook-v1 applies at PREMISE/SCRIPT; composing at SHOT drops it.
    hook = SKILLS.get("short-drama-hook-v1")
    composer = CreativeSkillComposer(stage=ContentStage.SHOT)
    resolution = composer.compose(skills=[hook])  # type: ignore[list-item]
    assert resolution.keys == []
    assert resolution.status is ResolutionStatus.RESOLVED


def test_composer_empty_stack_is_resolved() -> None:
    resolution = CreativeSkillComposer().compose(skills=[])
    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.keys == []


def test_composer_no_silent_override_of_earlier_skill() -> None:
    # Both skills are registered; composing in any order must not drop one.
    a = SKILLS.get("character-consistency-v1")
    b = SKILLS.get("continuity-guardian-v1")
    composer = CreativeSkillComposer()
    r1 = composer.compose(skills=[a, b])  # type: ignore[list-item]
    r2 = composer.compose(skills=[b, a])  # type: ignore[list-item]
    assert set(r1.keys) == {"character-consistency-v1", "continuity-guardian-v1"}
    assert set(r2.keys) == {"character-consistency-v1", "continuity-guardian-v1"}


def _make_conflicting(key: str, conflicts_with: str) -> CreativeSkillSpec:
    return CreativeSkillSpec(
        skill_key=key,
        skill_version="1",
        display_name=key,
        category=SkillCategory.STORY,
        description="conflict probe",
        strategy="probe",
        conflicts_with=[conflicts_with],
    )
