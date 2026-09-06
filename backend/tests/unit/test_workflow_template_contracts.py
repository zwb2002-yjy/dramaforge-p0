"""WF2 — Workflow Template contracts, registry and resolver tests."""

from __future__ import annotations

from dataclasses import replace

from app.director.workflows.contracts import (
    TemplateResolveSource,
    TemplateResolveStatus,
    WorkflowScope,
    WorkflowTemplateInputContract,
    WorkflowTemplateOutputContract,
    WorkflowTemplateRequest,
    WorkflowTemplateSpec,
    workflow_template_contract_hash,
)
from app.director.workflows.registry import WorkflowTemplateRegistry
from app.director.workflows.resolver import WorkflowTemplateResolver
from app.providers.capabilities import Capability


def _factory(**_: object) -> dict[str, object]:
    return {"template_key": "test", "nodes": []}


def _spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="test-dialogue-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Test dialogue",
        intent_tags=("dialogue", "two_character"),
        supported_mediums=("image", "video"),
        supported_character_count=(2, 2),
        duration_range=(3.0, 30.0),
        required_reference_roles=("character_a", "character_b"),
        optional_reference_roles=("wardrobe_a",),
        required_capabilities=(Capability.IMAGE_GENERATE, Capability.VIDEO_IMAGE_TO_VIDEO),
        quality_policy_id="live-dialogue-quality-v1",
        repair_policy_id="repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["character_a", "character_b"],
            max_reference_count=4,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["identity_review", "continuity_review"],
        ),
        graph_factory=_factory,
    )


def test_contract_hash_is_deterministic() -> None:
    assert workflow_template_contract_hash(_spec()) == workflow_template_contract_hash(_spec())


def test_contract_hash_changes_with_contract() -> None:
    base = _spec()
    changed = replace(_spec(), quality_policy_id="other-quality")
    assert workflow_template_contract_hash(base) != workflow_template_contract_hash(changed)


def test_registry_register_get_list() -> None:
    registry = WorkflowTemplateRegistry()
    spec = _spec()
    registry.register(spec)
    assert registry.get("test-dialogue-v1") == spec
    assert registry.list() == [spec]
    assert registry.contains("test-dialogue-v1")
    assert registry.get_versioned("test-dialogue-v1", "1.0.0") == spec


def test_registry_latest_version_wins() -> None:
    registry = WorkflowTemplateRegistry()
    registry.register(_spec())
    v2 = replace(_spec(), template_version="2.0.0", quality_policy_id="q2")
    registry.register(v2)
    assert registry.get("test-dialogue-v1").template_version == "2.0.0"


def test_registry_rejects_overwriting_frozen_contract() -> None:
    registry = WorkflowTemplateRegistry()
    registry.register(_spec())
    conflicting = replace(_spec(), quality_policy_id="different")
    try:
        registry.register(conflicting)
    except ValueError as exc:
        assert "contract mismatch" in str(exc)
        return
    raise AssertionError("expected ValueError for frozen-contract overwrite")


def test_registry_validate_requires_graph_factory() -> None:
    registry = WorkflowTemplateRegistry()
    spec = replace(_spec(), graph_factory=None)
    try:
        registry.register(spec)
    except ValueError as exc:
        assert "graph_factory" in str(exc)
        return
    raise AssertionError("expected ValueError for missing graph_factory")


def test_resolver_explicit_resolved() -> None:
    registry = WorkflowTemplateRegistry()
    registry.register(_spec())
    resolver = WorkflowTemplateResolver(registry)
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=2,
            reference_roles_present=["character_a", "character_b"],
            explicit_template_key="test-dialogue-v1",
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "test-dialogue-v1"
    assert resolution.source == TemplateResolveSource.EXPLICIT
    assert resolution.contract_hash == _spec().contract_hash


def test_resolver_explicit_unavailable_fails_closed() -> None:
    registry = WorkflowTemplateRegistry()
    registry.register(_spec())
    resolver = WorkflowTemplateResolver(registry)
    # Request a 2-char template for a 1-char scene: ineligible.
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue"],
            medium="video",
            character_count=1,
            explicit_template_key="test-dialogue-v1",
        )
    )
    assert resolution.status == TemplateResolveStatus.UNAVAILABLE
    assert resolution.resolved_template_key is None
    assert resolution.reason
    assert resolution.eligibility is not None
    assert resolution.eligibility.eligible is False


def test_resolver_explicit_unknown_template_is_unavailable() -> None:
    resolver = WorkflowTemplateResolver(WorkflowTemplateRegistry())
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue"],
            medium="video",
            character_count=1,
            explicit_template_key="does-not-exist",
        )
    )
    assert resolution.status == TemplateResolveStatus.UNAVAILABLE
    assert "not registered" in (resolution.reason or "")


def test_resolver_auto_selects_best_tag_match() -> None:
    registry = WorkflowTemplateRegistry()
    two_tag = WorkflowTemplateSpec(
        template_key="a-two-tag",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Two tag",
        intent_tags=("dialogue", "two_character"),
        supported_character_count=(1, 1),
        graph_factory=_factory,
    )
    one_tag = WorkflowTemplateSpec(
        template_key="b-one-tag",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="One tag",
        intent_tags=("dialogue",),
        supported_character_count=(1, 1),
        graph_factory=_factory,
    )
    registry.register(two_tag)
    registry.register(one_tag)
    resolver = WorkflowTemplateResolver(registry)
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=["dialogue", "two_character"],
            medium="video",
            character_count=1,
        )
    )
    assert resolution.status == TemplateResolveStatus.RESOLVED
    assert resolution.resolved_template_key == "a-two-tag"
    assert resolution.source == TemplateResolveSource.AUTO
