"""ModelSlot core invariants (spec §107 M1)."""

from __future__ import annotations

import pytest
from app.providers.capabilities import Capability
from app.providers.model_profiles.slots import (
    MODEL_SLOT_DEFINITIONS,
    P0_SLOTS,
    SIMPLE_MODE_SLOT_GROUPS,
    ModelSlot,
    slot_satisfies,
    slots_for_capability,
)


def test_every_slot_id_is_unique() -> None:
    ids = [str(definition.slot) for definition in MODEL_SLOT_DEFINITIONS.values()]
    assert len(ids) == len(set(ids))


def test_definition_key_matches_body() -> None:
    for slot, definition in MODEL_SLOT_DEFINITIONS.items():
        assert definition.slot == slot


def test_all_required_capabilities_are_valid() -> None:
    for slot, definition in MODEL_SLOT_DEFINITIONS.items():
        assert definition.required_capabilities, f"slot {slot} has no requirements"
        for capability in definition.required_capabilities:
            assert isinstance(capability, Capability)


def test_fallback_slot_graph_is_acyclic() -> None:
    visiting: set[ModelSlot] = set()
    visited: set[ModelSlot] = set()

    def visit(node: ModelSlot) -> None:
        if node in visited:
            return
        assert node not in visiting, f"fallback cycle at {node}"
        visiting.add(node)
        definition = MODEL_SLOT_DEFINITIONS.get(node)
        if definition is not None and definition.fallback_slot is not None:
            visit(definition.fallback_slot)
        visiting.discard(node)
        visited.add(node)

    for slot in MODEL_SLOT_DEFINITIONS:
        visit(slot)


def test_script_slot_requires_text_generate() -> None:
    assert slot_satisfies(ModelSlot.PLANNING_SCRIPT, Capability.TEXT_GENERATE)


def test_keyframe_slot_requires_image_generate() -> None:
    assert slot_satisfies(ModelSlot.VISUAL_KEYFRAME, Capability.IMAGE_GENERATE)


def test_video_slot_accepts_all_video_capabilities() -> None:
    for capability in (
        Capability.VIDEO_TEXT_TO_VIDEO,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        Capability.VIDEO_FIRST_LAST_FRAME,
        Capability.VIDEO_REFERENCE_TO_VIDEO,
    ):
        assert slot_satisfies(ModelSlot.VIDEO_SHOT, capability)


def test_slots_for_capability_round_trip() -> None:
    for slot, definition in MODEL_SLOT_DEFINITIONS.items():
        for capability in definition.required_capabilities:
            assert slot in slots_for_capability(capability)


def test_unknown_slot_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        ModelSlot("nope.unknown")


def test_p0_slots_are_a_subset() -> None:
    assert set(MODEL_SLOT_DEFINITIONS) >= P0_SLOTS
    assert ModelSlot.PLANNING_BRIEF in P0_SLOTS
    assert ModelSlot.VIDEO_SHOT in P0_SLOTS


def test_simple_mode_groups_cover_p0_slots() -> None:
    covered = {
        slot for group in SIMPLE_MODE_SLOT_GROUPS.values() for slot in group
    }
    for slot in P0_SLOTS:
        assert slot in covered, f"P0 slot {slot} missing from simple mode groups"
