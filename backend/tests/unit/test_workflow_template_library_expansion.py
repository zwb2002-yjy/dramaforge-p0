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
    # Removing unused builders must not invalidate already frozen planning contracts.
    assert {spec.template_key: spec.contract_hash for spec in registry.list()} == {
        "dialogue-post-dub-shot-v1": (
            "b0251a1c4d3b59dcf089b87d779570932fa73d7ccbe384efa595eb7f4b77e75c"
        ),
        "single-character-monologue-v1": (
            "b82871ce924bcfc8013c41c3cc30874271cb612ad4a5b679224a26806339e6cf"
        ),
        "two-character-dialogue-v1": (
            "3706349fadf687029a0fbfd549991518a8e54ebd5bd6c6e055287028ad1fd2d2"
        ),
        "action-motion-shot-v1": (
            "77e900434d1d87975051e37d769d4edc35363be90f725933613092f0e7ff57bd"
        ),
        "establishing-reaction-insert-v1": (
            "e5f2c17c89564f02c30a39162468e5b439aa7066c098b1fab8fd1ee40b808709"
        ),
        "montage-sequence-v1": ("c9da6dbe870eca4932fbd3b643c1e1a9510de794d9020f1c155721c3d72ca9e9"),
    }


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
