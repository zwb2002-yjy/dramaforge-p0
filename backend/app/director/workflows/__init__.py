"""Workflow Template framework (WF2).

Provider-neutral, deterministic, version-aware production workflow templates.
Registry and resolver never touch the network, credentials, models or fallback.
"""

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
from app.director.workflows.registry import WorkflowTemplateRegistry, build_registry
from app.director.workflows.resolver import WorkflowTemplateResolver

__all__ = [
    "GraphFactory",
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
    "build_workflow_registry",
    "dialogue_graph_factory",
    "dialogue_post_dub_spec",
    "get_default_registry",
    "build_registry",
    "workflow_template_contract_hash",
]
