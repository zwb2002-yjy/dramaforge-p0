"""Workflow Template library (WF3/WF4).

Registers the provider-neutral production templates that the Director /
Workbench execution path selects from.  Keeps the existing
``dialogue-post-dub-shot-v1`` graph definition byte-for-byte stable (legacy path
still imports ``app.director.production_templates`` directly); the registry is
the canonical place to resolve a template for a new shot/scene.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.director.production_templates import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
    dialogue_post_dub_definition,
)
from app.director.workflows.contracts import (
    WorkflowScope,
    WorkflowTemplateInputContract,
    WorkflowTemplateOutputContract,
    WorkflowTemplateSpec,
)
from app.director.workflows.registry import WorkflowTemplateRegistry
from app.providers.capabilities import Capability


def dialogue_graph_factory(
    *,
    character_reference_keys: Iterable[str],
    primary_character_reference_key: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Provider-neutral graph builder for ``dialogue-post-dub-shot-v1``.

    Delegates to the existing stable definition so WF3 does not rewrite any
    graph node.  Golden behavior and quality policy are preserved.
    """
    return dialogue_post_dub_definition(
        character_reference_keys=character_reference_keys,
        primary_character_reference_key=primary_character_reference_key,
        context=context,
    )


def dialogue_post_dub_spec() -> WorkflowTemplateSpec:
    """Registered spec for the existing dialogue-post-dub-shot-v1 template."""
    return WorkflowTemplateSpec(
        template_key=DIALOGUE_POST_DUB_SHOT_V1,
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Dialogue (post-dub) shot",
        description=(
            "Single on-screen character dialogue shot with Mandarin voice and "
            "subtitle composited post-dub."
        ),
        intent_tags=("dialogue", "single_character"),
        supported_mediums=("image", "video"),
        supported_character_count=(1, 1),
        duration_range=(3.0, 30.0),
        required_reference_roles=("character",),
        optional_reference_roles=(),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            Capability.AUDIO_TTS,
        ),
        quality_policy_id=QUALITY_POLICY_V1,
        repair_policy_id="live-dialogue-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["character"],
            min_reference_count=1,
            max_reference_count=1,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video", "voice", "subtitle", "composite"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["identity_review", "video_drift_review", "continuity_review"],
        ),
        graph_factory=dialogue_graph_factory,
    )


def build_workflow_registry() -> WorkflowTemplateRegistry:
    """Return a fresh registry seeded with the published workflow templates."""
    registry = WorkflowTemplateRegistry()
    for spec in _template_specs():
        registry.register(spec)
    return registry


def get_default_registry() -> WorkflowTemplateRegistry:
    """Fresh default registry built from the published template specs.

    Deterministic and code-versioned: ``template_key + template_version +
    contract_hash`` reproduce execution without a database template catalog.
    """
    return build_workflow_registry()


def _template_specs() -> list[WorkflowTemplateSpec]:
    # WF3 registers the existing dialogue template.  WF4 appends the new
    # baseline shot templates below.
    return [dialogue_post_dub_spec()]
