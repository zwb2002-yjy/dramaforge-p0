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
    "max_subject_references",
    "participation_director_state",
    "required_subject_references",
    "workflow_template_contract_hash",
]
