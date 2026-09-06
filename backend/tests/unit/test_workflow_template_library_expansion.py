"""WF4 — baseline shot template library expansion."""

from __future__ import annotations

from app.director.workflows.contracts import (
    TemplateResolveStatus,
    WorkflowTemplateRequest,
)
from app.director.workflows.library import get_default_registry
from app.director.workflows.resolver import WorkflowTemplateResolver

EXPECTED_KEYS = {
    "dialogue-post-dub-shot-v1",
    "single-character-monologue-v1",
    "two-character-dialogue-v1",
    "action-motion-shot-v1",
    "establishing-reaction-insert-v1",
    "montage-sequence-v1",
}


def test_default_registry_contains_all_baseline_templates() -> None:
    registry = get_default_registry()
    keys = set(registry.keys())
    assert keys >= EXPECTED_KEYS
    # Every template must carry a distinct contract hash (no copy-paste).
    specs = [registry.get(key) for key in EXPECTED_KEYS]
    assert all(spec is not None for spec in specs)
    hashes = {spec.contract_hash for spec in specs if spec is not None}
    assert len(hashes) == len(EXPECTED_KEYS)


def test_resolver_monologue() -> None:
    resolver = WorkflowTemplateResolver(get_default_registry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["monologue", "dialogue"],
            medium="video",
            character_count=1,
            reference_roles_present=["character"],
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "single-character-monologue-v1"


def test_resolver_two_character_dialogue() -> None:
    resolver = WorkflowTemplateResolver(get_default_registry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=2,
            reference_roles_present=["character_a", "character_b"],
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "two-character-dialogue-v1"


def test_resolver_environment_establishing() -> None:
    resolver = WorkflowTemplateResolver(get_default_registry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["establishing", "environment"],
            medium="video",
            character_count=0,
            reference_roles_present=["environment"],
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "establishing-reaction-insert-v1"


def test_resolver_high_motion_action() -> None:
    resolver = WorkflowTemplateResolver(get_default_registry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["action", "motion"],
            medium="video",
            character_count=1,
            reference_roles_present=["character"],
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "action-motion-shot-v1"


def test_resolver_explicit_override_fails_closed() -> None:
    resolver = WorkflowTemplateResolver(get_default_registry())
    # Explicitly request a 2-char template for a 0-char establishing scene.
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=0,
            explicit_template_key="two-character-dialogue-v1",
        )
    )
    assert resolution.status == TemplateResolveStatus.UNAVAILABLE
    assert resolution.resolved_template_key is None
    # A different eligible template must NOT be silently substituted.
    assert resolution.requested_template_key == "two-character-dialogue-v1"
