"""Workflow Template framework (WF2).

Provider-neutral, deterministic, version-aware production workflow templates.
Registry and resolver never touch the network, credentials, models or fallback.
"""

from app.director.workflows.character_participation import (
    MAX_VISIBLE_CONTROLLED_CHARACTERS,
    DialogueRole,
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
    participation_director_state,
)
from app.director.workflows.contracts import (
    GraphFactory,
    TemplateResolveSource,
    TemplateResolveStatus,
    WorkflowScope,
    WorkflowTemplateEligibility,
    WorkflowTemplateInputContract,
    WorkflowTemplateOutputContract,
    WorkflowTemplateRequest,
    WorkflowTemplateResolution,
    WorkflowTemplateSpec,
    workflow_template_contract_hash,
)
from app.director.workflows.layered_planning import (
    PLATFORM_MAX_SCENES_PER_EPISODE,
    PLATFORM_MAX_SHOTS_PER_SCENE,
    EpisodePlanPayload,
    ProductionProfile,
    ScenePlanPayload,
    SceneStoryboardPlanPayload,
    ShotPlanPayload,
)
from app.director.workflows.layered_production_service import (
    materialize_episode_plan,
    materialize_scene_storyboard,
    require_episode_scene,
)
from app.director.workflows.library import (
    build_workflow_registry,
    dialogue_graph_factory,
    dialogue_post_dub_spec,
    get_default_registry,
)
from app.director.workflows.quality_report import (
    IdentityResultStatus,
    MultiCharacterIdentityReport,
    PerCharacterIdentityResult,
)
from app.director.workflows.reference_capability import (
    MultiCharacterCapabilityStatus,
    ReferenceCapabilityAssessment,
    assess_multi_character_capability,
    max_subject_references,
    required_subject_references,
)
from app.director.workflows.registry import WorkflowTemplateRegistry, build_registry
from app.director.workflows.resolver import WorkflowTemplateResolver
from app.director.workflows.shot_complexity import (
    CameraMotion,
    ComplexityLevel,
    ComplexityStrategy,
    ShotComplexityAssessment,
    ShotDirectorIntent,
    assess_shot_complexity,
    complexity_director_state,
)

__all__ = [
    "DialogueRole",
    "GraphFactory",
    "IdentityResultStatus",
    "MAX_VISIBLE_CONTROLLED_CHARACTERS",
    "MultiCharacterCapabilityStatus",
    "MultiCharacterIdentityReport",
    "PerCharacterIdentityResult",
    "ReferenceCapabilityAssessment",
    "ScreenRole",
    "ShotCharacterParticipation",
    "ShotParticipationPlan",
    "TemplateResolveSource",
    "TemplateResolveStatus",
    "WorkflowScope",
    "WorkflowTemplateEligibility",
    "WorkflowTemplateInputContract",
    "WorkflowTemplateOutputContract",
    "WorkflowTemplateRegistry",
    "WorkflowTemplateRequest",
    "WorkflowTemplateResolution",
    "WorkflowTemplateResolver",
    "WorkflowTemplateSpec",
    "CameraMotion",
    "ComplexityLevel",
    "EpisodePlanPayload",
    "PLATFORM_MAX_SCENES_PER_EPISODE",
    "PLATFORM_MAX_SHOTS_PER_SCENE",
    "ProductionProfile",
    "ScenePlanPayload",
    "SceneStoryboardPlanPayload",
    "ShotPlanPayload",
    "ComplexityStrategy",
    "ShotComplexityAssessment",
    "ShotDirectorIntent",
    "assess_multi_character_capability",
    "assess_shot_complexity",
    "build_registry",
    "build_workflow_registry",
    "complexity_director_state",
    "dialogue_graph_factory",
    "dialogue_post_dub_spec",
    "get_default_registry",
    "materialize_episode_plan",
    "materialize_scene_storyboard",
    "max_subject_references",
    "participation_director_state",
    "require_episode_scene",
    "required_subject_references",
    "workflow_template_contract_hash",
]
