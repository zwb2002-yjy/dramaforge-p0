"""WF3 — dialogue-post-dub-shot-v1 template migration into the registry."""

from __future__ import annotations

from app.director.workflows.library import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
    dialogue_post_dub_spec,
    get_default_registry,
)


def test_dialogue_template_is_registered() -> None:
    registry = get_default_registry()
    spec = registry.get(DIALOGUE_POST_DUB_SHOT_V1)
    assert spec is not None
    assert spec.template_version == "1.0.0"
    assert spec.quality_policy_id == QUALITY_POLICY_V1


def test_dialogue_spec_contract_hash_is_stable() -> None:
    registry = get_default_registry()
    spec = registry.get(DIALOGUE_POST_DUB_SHOT_V1)
    assert spec is not None
    assert spec.contract_hash == dialogue_post_dub_spec().contract_hash
