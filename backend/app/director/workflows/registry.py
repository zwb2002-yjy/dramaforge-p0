"""Workflow Template registry (WF2).

Provider-neutral, deterministic and version-aware.  Holds registered
``WorkflowTemplateSpec`` instances in code; it must never touch the network,
read credentials, choose a model or fall back to another provider/template.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable

from app.director.workflows.contracts import (
    WorkflowTemplateEligibility,
    WorkflowTemplateRequest,
    WorkflowTemplateSpec,
)


class WorkflowTemplateRegistry:
    """In-memory registration and eligibility lookup for production templates."""

    def __init__(self) -> None:
        # template_key -> {template_version -> spec}; insertion order preserved.
        self._entries: dict[str, dict[str, WorkflowTemplateSpec]] = {}
        self._keys: dict[str, WorkflowTemplateSpec] = {}

    def register(self, spec: WorkflowTemplateSpec) -> WorkflowTemplateSpec:
        """Register (or replace) a template version.

        Deterministic: re-registering the same version with the same contract is
        idempotent; re-registering a different contract under the same
        ``template_key`` + ``version`` raises (fail closed, no silent overwrite).
        """
        self.validate(spec)
        versions = self._entries.setdefault(spec.template_key, {})
        existing = versions.get(spec.template_version)
        if existing is not None and existing.contract_hash != spec.contract_hash:
            raise ValueError(
                f"template contract mismatch for {spec.template_key}@"
                f"{spec.template_version}: refusing to overwrite a frozen contract"
            )
        versions[spec.template_version] = spec
        # Keep ``_keys`` pointing at the highest registered version.
        self._keys[spec.template_key] = max(
            versions.values(), key=lambda s: s.template_version
        )
        return spec

    def get(self, template_key: str) -> WorkflowTemplateSpec | None:
        """Return the highest registered version for ``template_key``."""
        return self._keys.get(template_key)

    def get_versioned(
        self, template_key: str, template_version: str
    ) -> WorkflowTemplateSpec | None:
        return self._entries.get(template_key, {}).get(template_version)

    def list(self) -> builtins.list[WorkflowTemplateSpec]:
        """All registered templates (highest version per key, insertion order)."""
        return list(self._keys.values())

    def keys(self) -> builtins.list[str]:
        return list(self._keys)

    def contains(self, template_key: str) -> bool:
        return template_key in self._entries

    def eligible(
        self, request: WorkflowTemplateRequest
    ) -> builtins.list[tuple[WorkflowTemplateSpec, WorkflowTemplateEligibility]]:
        """All registered templates eligible for ``request`` (provider-neutral)."""
        results: builtins.list[tuple[WorkflowTemplateSpec, WorkflowTemplateEligibility]] = []
        for spec in self.list():
            eligibility = self._evaluate(spec, request)
            if eligibility.eligible:
                results.append((spec, eligibility))
        return results

    def evaluate(
        self, spec: WorkflowTemplateSpec, request: WorkflowTemplateRequest
    ) -> WorkflowTemplateEligibility:
        """Public eligibility check for one spec (no I/O, deterministic)."""
        return self._evaluate(spec, request)

    def validate(self, spec: WorkflowTemplateSpec) -> None:
        """Validate that a spec is well-formed (no I/O)."""
        if spec.graph_factory is None:
            raise ValueError(f"template {spec.template_key} must provide a graph_factory")

    def _evaluate(
        self, spec: WorkflowTemplateSpec, request: WorkflowTemplateRequest
    ) -> WorkflowTemplateEligibility:
        reasons: list[str] = []
        capability_gaps: list[str] = []
        matched_tags: list[str] = []

        # Scope parity.
        if spec.scope.value == "shot" and request.scene_scope:
            reasons.append(f"template {spec.template_key} is shot-scoped")
        if spec.scope.value == "scene" and not request.scene_scope:
            reasons.append(f"template {spec.template_key} is scene-scoped")

        # Intent overlap: a template is eligible only when at least one tag matches.
        tag_overlap = set(spec.intent_tags) & set(request.intent_tags)
        if tag_overlap:
            matched_tags.extend(sorted(tag_overlap))
        elif spec.intent_tags:
            # Only surface this as a rule when the template actually has tags.
            reasons.append("no intent tag overlap")

        # Medium.
        if request.medium not in spec.supported_mediums:
            reasons.append(
                f"medium {request.medium!r} not in {list(spec.supported_mediums)!r}"
            )

        # Character count.
        min_char, max_char = spec.supported_character_count
        if not (min_char <= request.character_count <= max_char):
            reasons.append(
                f"character count {request.character_count} outside "
                f"[{min_char}, {max_char}]"
            )

        # Reference roles.
        present = set(request.reference_roles_present)
        for role in spec.required_reference_roles:
            if role not in present:
                reasons.append(f"missing required reference role {role!r}")

        # Capability gaps (declared required capabilities not matched by request).
        # The resolver only uses the *request* here; real per-model capability
        # negotiation stays in the execution planner (WF6).  We record required
        # capabilities as gaps only when the request declares none present.
        if spec.required_capabilities and not request.intent_tags:
            capability_gaps.append("request declares no capability evidence")

        eligible = not reasons and not capability_gaps
        return WorkflowTemplateEligibility(
            template_key=spec.template_key,
            eligible=eligible,
            reasons=reasons,
            capability_gaps=capability_gaps,
            matched_intent_tags=matched_tags,
        )


def build_registry(specs: Iterable[WorkflowTemplateSpec]) -> WorkflowTemplateRegistry:
    """Convenience builder that registers every spec in ``specs`` in order."""
    registry = WorkflowTemplateRegistry()
    for spec in specs:
        registry.register(spec)
    return registry
