"""Workflow Template library (WF3/WF4).

Registers the provider-neutral production templates that the Director /
Workbench execution path selects from.  Keeps the existing
``dialogue-post-dub-shot-v1`` graph definition byte-for-byte stable (legacy path
still imports ``app.director.production_templates`` directly); the registry is
the canonical place to resolve a template for a new shot/scene.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.director.workflows.contracts import (
    WorkflowScope,
    WorkflowTemplateInputContract,
    WorkflowTemplateOutputContract,
    WorkflowTemplateSpec,
)
from app.director.workflows.registry import WorkflowTemplateRegistry
from app.director.workflows.template_nodes import (
    action_motion_shot_definition,
    establishing_reaction_insert_definition,
    montage_sequence_definition,
    single_character_monologue_definition,
    two_character_dialogue_definition,
)
from app.production.templates import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
    dialogue_post_dub_definition,
)
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


def single_character_monologue_spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="single-character-monologue-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Single-character monologue",
        description=(
            "Continuous single-character performance; voice is primary, no "
            "timed subtitle track; repair emphasizes identity drift."
        ),
        intent_tags=("monologue", "dialogue", "single_character"),
        supported_mediums=("image", "video"),
        supported_character_count=(1, 1),
        duration_range=(3.0, 60.0),
        required_reference_roles=("character",),
        optional_reference_roles=(),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            Capability.AUDIO_TTS,
        ),
        quality_policy_id="monologue-quality-v1",
        repair_policy_id="monologue-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["character"],
            min_reference_count=1,
            max_reference_count=1,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video", "voice", "composite"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["identity_review", "video_drift_review", "continuity_review"],
        ),
        graph_factory=single_character_monologue_definition,
    )


def two_character_dialogue_spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="two-character-dialogue-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Two-character dialogue",
        description=(
            "Two on-screen characters with per-character subject reference and "
            "per-character voice tracks; identity review is composed from both."
        ),
        intent_tags=("dialogue", "two_character"),
        supported_mediums=("image", "video"),
        supported_character_count=(2, 2),
        duration_range=(3.0, 60.0),
        required_reference_roles=("character_a", "character_b"),
        optional_reference_roles=("wardrobe_a", "wardrobe_b"),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            Capability.AUDIO_TTS,
        ),
        quality_policy_id="two-character-dialogue-quality-v1",
        repair_policy_id="two-character-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["character_a", "character_b"],
            min_reference_count=2,
            max_reference_count=4,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video", "voice", "composite"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["identity_review", "video_drift_review", "continuity_review"],
        ),
        graph_factory=two_character_dialogue_definition,
    )


def action_motion_shot_spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="action-motion-shot-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Action / motion shot",
        description=(
            "High-motion shot: no dialogue voice, motion and body-anatomy "
            "repair emphasis."
        ),
        intent_tags=("action", "motion", "physical"),
        supported_mediums=("image", "video"),
        supported_character_count=(1, 4),
        duration_range=(1.0, 20.0),
        required_reference_roles=("character",),
        optional_reference_roles=("environment", "wardrobe"),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
        ),
        quality_policy_id="action-motion-quality-v1",
        repair_policy_id="action-motion-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["character"],
            min_reference_count=1,
            max_reference_count=5,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video", "composite"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["identity_review", "video_drift_review", "continuity_review"],
        ),
        graph_factory=action_motion_shot_definition,
    )


def establishing_reaction_insert_spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="establishing-reaction-insert-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SHOT,
        display_name="Establishing / reaction / insert",
        description=(
            "Low character-control shot: environment establishing, reaction or "
            "object insert.  No identity review; environment reference primary."
        ),
        intent_tags=("establishing", "reaction", "insert", "environment"),
        supported_mediums=("image", "video"),
        supported_character_count=(0, 4),
        duration_range=(1.0, 20.0),
        required_reference_roles=("environment",),
        optional_reference_roles=("style",),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
        ),
        quality_policy_id="establishing-quality-v1",
        repair_policy_id="establishing-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["environment"],
            min_reference_count=1,
            max_reference_count=3,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["keyframe", "video", "composite"],
            formal_outputs=["formal_keyframe", "formal_video"],
            review_nodes=["video_drift_review", "continuity_review"],
        ),
        graph_factory=establishing_reaction_insert_definition,
    )


def montage_sequence_spec() -> WorkflowTemplateSpec:
    return WorkflowTemplateSpec(
        template_key="montage-sequence-v1",
        template_version="1.0.0",
        scope=WorkflowScope.SCENE,
        display_name="Montage sequence",
        description=(
            "Scene-scope montage: multiple short shot contributions assembled "
            "into one composite."
        ),
        intent_tags=("montage", "sequence"),
        supported_mediums=("image", "video"),
        supported_character_count=(0, 6),
        duration_range=(3.0, 120.0),
        required_reference_roles=("environment",),
        optional_reference_roles=("style", "character"),
        required_capabilities=(
            Capability.IMAGE_GENERATE,
            Capability.VIDEO_IMAGE_TO_VIDEO,
        ),
        quality_policy_id="montage-sequence-quality-v1",
        repair_policy_id="montage-repair-v1",
        input_contract=WorkflowTemplateInputContract(
            required_reference_roles=["environment"],
            min_reference_count=1,
            max_reference_count=8,
        ),
        output_contract=WorkflowTemplateOutputContract(
            artifact_kinds=["montage", "video"],
            formal_outputs=["formal_video"],
            review_nodes=["continuity_review"],
        ),
        graph_factory=montage_sequence_definition,
    )


def _template_specs() -> list[WorkflowTemplateSpec]:
    # WF3 registers the existing dialogue template; WF4 adds the baseline
    # shot/scene template library.
    return [
        dialogue_post_dub_spec(),
        single_character_monologue_spec(),
        two_character_dialogue_spec(),
        action_motion_shot_spec(),
        establishing_reaction_insert_spec(),
        montage_sequence_spec(),
    ]
