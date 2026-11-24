"""Selected creative methods stay bounded, frozen and subordinate to user intent."""

from __future__ import annotations

import copy
import json

import pytest
from app.director.creative_capabilities.agent_skills import build_agent_skill_context
from app.director.creative_capabilities.contracts import ContentStage
from app.director.creative_capabilities.packs_library import GENRE_PROFILES
from app.director.creative_capabilities.registry import build_skill_registry
from app.director.creative_capabilities.skill_library import (
    CHARACTER_CONSISTENCY,
    DIALOGUE_SCENE_DIRECTION,
    SHORT_DRAMA_HOOK,
)


def test_profile_selection_loads_existing_skill_content_and_identity() -> None:
    context = build_agent_skill_context(
        selected_skill_ids=[DIALOGUE_SCENE_DIRECTION.skill_key], profile_version=4
    )
    guidance = context["skill_guidance"][0]
    assert guidance["strategy"] == DIALOGUE_SCENE_DIRECTION.strategy
    assert guidance["skill_version"] == DIALOGUE_SCENE_DIRECTION.skill_version
    assert guidance["contract_hash"] == DIALOGUE_SCENE_DIRECTION.contract_hash
    assert guidance["inputs"][0]["field"] == "speaker_turn"
    assert context["profile_version"] == 4
    assert context["authority"]["grants_tool_permissions"] is False
    assert context["authority"]["bypasses_user_gates"] is False


def test_explicit_subset_never_loads_an_unselected_or_recommended_skill() -> None:
    context = build_agent_skill_context(
        selected_skill_ids=[SHORT_DRAMA_HOOK.skill_key, CHARACTER_CONSISTENCY.skill_key],
        requested_skill_ids=[CHARACTER_CONSISTENCY.skill_key],
        genre=GENRE_PROFILES[0],
    )
    assert [row["skill_key"] for row in context["skill_guidance"]] == [
        CHARACTER_CONSISTENCY.skill_key
    ]
    with pytest.raises(ValueError, match="not selected"):
        build_agent_skill_context(
            selected_skill_ids=[SHORT_DRAMA_HOOK.skill_key],
            requested_skill_ids=[DIALOGUE_SCENE_DIRECTION.skill_key],
        )
    assert build_agent_skill_context(selected_skill_ids=[])["skill_guidance"] == []


@pytest.mark.parametrize(
    "selected,requested",
    [(["missing-skill"], None), (["missing-skill"], []), ([], ["missing-skill"])],
)
def test_unknown_skill_never_silently_falls_back(selected, requested) -> None:
    with pytest.raises(ValueError):
        build_agent_skill_context(selected_skill_ids=selected, requested_skill_ids=requested)


def test_existing_compiler_preserves_all_four_value_precedence_layers() -> None:
    context = build_agent_skill_context(
        selected_skill_ids=[SHORT_DRAMA_HOOK.skill_key],
        genre=GENRE_PROFILES[0],
        project_context={"hook_strategy": "project", "scene_pacing": "project pacing"},
        accepted_proposal={"hook_strategy": "accepted", "turn_frequency": "accepted turn"},
        user_intent={"hook_strategy": "user"},
    )
    assert context["effective_values"]["hook_strategy"] == "user"
    assert context["effective_values"]["turn_frequency"] == "accepted turn"
    assert context["effective_values"]["scene_pacing"] == "project pacing"
    assert context["effective_values"]["dialogue_density"] == GENRE_PROFILES[0].dialogue_density
    assert context["value_sources"]["hook_strategy"] == "user_confirmed"
    assert context["value_sources"]["turn_frequency"] == "accepted_proposal"
    assert context["value_sources"]["scene_pacing"] == "project_override"
    assert context["value_sources"]["dialogue_density"] == "pack_default"


def test_snapshot_is_stable_and_detached_from_profile_inputs_and_registry() -> None:
    spec = CHARACTER_CONSISTENCY.model_copy(deep=True)
    registry = build_skill_registry([spec])
    selected = [spec.skill_key]
    intent = {"wardrobe": {"color": "blue"}}
    original = copy.deepcopy(intent)
    context = build_agent_skill_context(
        selected_skill_ids=selected, user_intent=intent, registry=registry, profile_version=1
    )
    assert context == build_agent_skill_context(
        selected_skill_ids=list(selected),
        user_intent=original,
        registry=registry,
        profile_version=1,
    )
    frozen = json.dumps(context, sort_keys=True)
    selected.clear()
    intent["wardrobe"]["color"] = "red"
    spec.quality_hints.append("changed after freezing")
    assert json.dumps(context, sort_keys=True) == frozen
    changed = build_agent_skill_context(
        selected_skill_ids=[spec.skill_key],
        user_intent=original,
        registry=registry,
        profile_version=2,
    )
    assert changed["context_hash"] != context["context_hash"]


def test_stage_filter_is_visible_and_explicit_mismatch_is_rejected() -> None:
    selected = [SHORT_DRAMA_HOOK.skill_key, DIALOGUE_SCENE_DIRECTION.skill_key]
    context = build_agent_skill_context(selected_skill_ids=selected, stage=ContentStage.SHOT)
    assert context["inactive_skill_ids"] == [SHORT_DRAMA_HOOK.skill_key]
    assert [row["skill_key"] for row in context["skill_guidance"]] == [
        DIALOGUE_SCENE_DIRECTION.skill_key
    ]
    with pytest.raises(ValueError, match="current stage"):
        build_agent_skill_context(
            selected_skill_ids=selected,
            requested_skill_ids=[SHORT_DRAMA_HOOK.skill_key],
            stage=ContentStage.SHOT,
        )


def test_conflicting_registered_skills_are_rejected_without_removing_one_side() -> None:
    conflicting = CHARACTER_CONSISTENCY.model_copy(
        update={"conflicts_with": [DIALOGUE_SCENE_DIRECTION.skill_key]}
    )
    with pytest.raises(ValueError, match="conflict"):
        build_agent_skill_context(
            selected_skill_ids=[conflicting.skill_key, DIALOGUE_SCENE_DIRECTION.skill_key],
            registry=build_skill_registry([conflicting, DIALOGUE_SCENE_DIRECTION]),
        )


@pytest.mark.parametrize("value", [float("nan"), object(), {"not", "json"}])
def test_non_json_context_is_rejected(value) -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        build_agent_skill_context(selected_skill_ids=[], user_intent={"value": value})


def test_byte_limit_rejects_instead_of_truncating_user_constraints_or_skill_contracts() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        build_agent_skill_context(
            selected_skill_ids=[], user_intent={"constraint": "中" * 1000}, max_bytes=1200
        )
    with pytest.raises(ValueError, match="byte limit"):
        build_agent_skill_context(selected_skill_ids=[SHORT_DRAMA_HOOK.skill_key], max_bytes=100)


@pytest.mark.parametrize("version", [0, -1, True])
def test_invalid_profile_version_is_rejected(version) -> None:
    with pytest.raises(ValueError, match="profile version"):
        build_agent_skill_context(selected_skill_ids=[], profile_version=version)


def test_repeated_selection_and_string_instead_of_list_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        build_agent_skill_context(selected_skill_ids=[SHORT_DRAMA_HOOK.skill_key] * 2)
    with pytest.raises(ValueError, match="selection"):
        build_agent_skill_context(selected_skill_ids=SHORT_DRAMA_HOOK.skill_key)
