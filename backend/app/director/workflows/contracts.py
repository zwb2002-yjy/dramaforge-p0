"""Workflow Template typed contracts (WF2).

These are provider-neutral, deterministic, version-aware contracts that describe
*how a shot/scene should be produced* — not a prompt and not a Provider call.

A template is frozen by ``contract_hash`` (computed from the serializable field
subset, excluding the ``graph_factory`` callable).  Retry / Resume must use the
same frozen template identity (G-WF-03); the registry is forbidden from doing
Provider requests, credential access, model selection or fallback model work.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.providers.capabilities import Capability

# A provider-neutral graph definition builder.  The concrete signature varies by
# template but always returns a ProductionGraph ``definition`` dict.
GraphFactory = Callable[..., dict[str, object]]


class WorkflowScope(StrEnum):
    SHOT = "shot"
    SCENE = "scene"


class TemplateResolveStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNAVAILABLE = "UNAVAILABLE"


class TemplateResolveSource(StrEnum):
    EXPLICIT = "explicit"
    AUTO = "auto"
    DEFAULT = "default"


class WorkflowTemplateEligibility(BaseModel):
    """Result of checking a shot/scene intent against one template.

    ``eligible=False`` is never silently upgraded: the resolver returns
    ``UNAVAILABLE`` unless the user explicitly opted into a registered,
    approved approximation strategy (the only path to ``approximate``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    template_key: str
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    capability_gaps: list[str] = Field(default_factory=list)
    matched_intent_tags: list[str] = Field(default_factory=list)
    approximate: bool = False
    approximate_strategy: str | None = None


class WorkflowTemplateInputContract(BaseModel):
    """Declared shot/scene input reference shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_reference_roles: list[str] = Field(default_factory=list)
    optional_reference_roles: list[str] = Field(default_factory=list)
    min_reference_count: int = 0
    max_reference_count: int | None = None
    max_average_reference_per_role: int | None = None


class WorkflowTemplateOutputContract(BaseModel):
    """Declared formal artifact outputs the graph is expected to produce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_kinds: list[str] = Field(default_factory=list)
    formal_outputs: list[str] = Field(default_factory=list)
    review_nodes: list[str] = Field(default_factory=list)


def _canonical_payload(spec: WorkflowTemplateSpec) -> dict[str, object]:
    """Serializable, order-insensitive subset used for the contract hash."""
    return {
        "template_key": spec.template_key,
        "template_version": spec.template_version,
        "scope": spec.scope.value,
        "display_name": spec.display_name,
        "intent_tags": sorted(spec.intent_tags),
        "supported_mediums": sorted(spec.supported_mediums),
        "supported_character_count": list(spec.supported_character_count),
        "duration_range": list(spec.duration_range),
        "required_reference_roles": sorted(spec.required_reference_roles),
        "optional_reference_roles": sorted(spec.optional_reference_roles),
        "required_capabilities": sorted(c.value for c in spec.required_capabilities),
        "optional_capabilities": sorted(c.value for c in spec.optional_capabilities),
        "quality_policy_id": spec.quality_policy_id,
        "repair_policy_id": spec.repair_policy_id,
        "input_contract": spec.input_contract.model_dump(mode="json"),
        "output_contract": spec.output_contract.model_dump(mode="json"),
    }


def workflow_template_contract_hash(spec: WorkflowTemplateSpec) -> str:
    """Deterministic sha256 over the frozen template contract subset."""
    canonical = json.dumps(
        _canonical_payload(spec),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkflowTemplateSpec:
    """Typed manifest for one versioned production workflow template.

    ``graph_factory`` is deliberately excluded from the contract hash (and from
    any serialization): it is the code that builds the ProductionGraph, while
    ``contract_hash`` guarantees the *semantic contract* is frozen.
    """

    template_key: str
    template_version: str
    scope: WorkflowScope
    display_name: str
    description: str = ""
    intent_tags: tuple[str, ...] = ()
    supported_mediums: tuple[str, ...] = ("image", "video")
    supported_character_count: tuple[int, int] = (1, 1)
    duration_range: tuple[float, float] = (1.0, 30.0)
    required_reference_roles: tuple[str, ...] = ()
    optional_reference_roles: tuple[str, ...] = ()
    required_capabilities: tuple[Capability, ...] = ()
    optional_capabilities: tuple[Capability, ...] = ()
    input_contract: WorkflowTemplateInputContract = field(
        default_factory=WorkflowTemplateInputContract
    )
    output_contract: WorkflowTemplateOutputContract = field(
        default_factory=WorkflowTemplateOutputContract
    )
    quality_policy_id: str = ""
    repair_policy_id: str = ""
    graph_factory: GraphFactory | None = None

    @property
    def contract_hash(self) -> str:
        return workflow_template_contract_hash(self)

    @property
    def capabilities(self) -> list[str]:
        """Business capability labels this template requires (provider-neutral)."""
        return [capability.value for capability in self.required_capabilities]

    def __post_init__(self) -> None:
        if not self.template_key:
            raise ValueError("template_key must not be empty")
        if not self.template_version:
            raise ValueError("template_version must not be empty")
        min_char, max_char = self.supported_character_count
        if min_char < 0 or max_char < min_char:
            raise ValueError("supported_character_count must be an ascending non-negative range")
        min_dur, max_dur = self.duration_range
        if min_dur <= 0 or max_dur < min_dur:
            raise ValueError("duration_range must be an ascending positive range")
        if self.scope is WorkflowScope.SCENE and not self.intent_tags:
            raise ValueError("scene-scope template must declare intent_tags")


class WorkflowTemplateRequest(BaseModel):
    """Normalized resolver input — no DB, no provider, no credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_tags: list[str] = Field(default_factory=list)
    medium: str = "video"
    character_count: int = 1
    reference_roles_present: list[str] = Field(default_factory=list)
    explicit_template_key: str | None = None
    scene_scope: bool = False


class WorkflowTemplateResolution(BaseModel):
    """Result of resolving a requested template for a shot/scene intent.

    ``status`` is ``RESOLVED`` or ``UNAVAILABLE``.  An explicit request that
    cannot be honored always fails closed (``UNAVAILABLE``) — never a silent
    fallback to another template (G-WF-04).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_template_key: str | None = None
    resolved_template_key: str | None = None
    template_version: str | None = None
    status: TemplateResolveStatus
    source: TemplateResolveSource
    reason: str | None = None
    contract_hash: str | None = None
    eligibility: WorkflowTemplateEligibility | None = None
