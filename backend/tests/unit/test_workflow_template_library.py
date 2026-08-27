"""WF3 — dialogue-post-dub-shot-v1 template migration into the registry."""

from __future__ import annotations

from app.director.production_templates import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
    dialogue_post_dub_definition,
)
from app.director.workflows.library import (
    dialogue_graph_factory,
    dialogue_post_dub_spec,
    get_default_registry,
)


def test_dialogue_template_is_registered() -> None:
    registry = get_default_registry()
    spec = registry.get(DIALOGUE_POST_DUB_SHOT_V1)
    assert spec is not None
    assert spec.template_version == "1.0.0"
    assert spec.quality_policy_id == QUALITY_POLICY_V1
    assert spec.graph_factory is not None


def test_dialogue_definition_unchanged() -> None:
    """The registry factory must reproduce the existing graph byte-for-byte."""
    ref_keys = ["character_a", "character_b"]
    context = {"scope_id": "shot-1", "quality_policy": QUALITY_POLICY_V1}
    graph = dialogue_graph_factory(
        character_reference_keys=ref_keys,
        primary_character_reference_key="character_a",
        context=context,
    )
    expected = dialogue_post_dub_definition(
        character_reference_keys=ref_keys,
        primary_character_reference_key="character_a",
        context=context,
    )
    assert graph == expected
    assert graph["template_key"] == DIALOGUE_POST_DUB_SHOT_V1
    assert graph["template_version"] == "1.0.0"
    assert graph["quality_policy_id"] == QUALITY_POLICY_V1
    keys = [node["key"] for node in graph["nodes"]]
    assert "keyframe" in keys
    assert "identity_review" in keys
    assert "video" in keys
    assert "composite" in keys
    assert "continuity_review" in keys
    assert keys[:2] == ["character_a", "character_b"]


def test_dialogue_spec_contract_hash_is_stable() -> None:
    registry = get_default_registry()
    spec = registry.get(DIALOGUE_POST_DUB_SHOT_V1)
    assert spec is not None
    assert spec.contract_hash == dialogue_post_dub_spec().contract_hash
