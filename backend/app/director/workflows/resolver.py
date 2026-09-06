"""Workflow Template resolver (WF2).

Translates a normalized ``WorkflowTemplateRequest`` into a
``WorkflowTemplateResolution``.  Fails closed: an explicit template that is not
eligible is never replaced by a different template (G-WF-04).
"""

from __future__ import annotations

from app.director.workflows.contracts import (
    TemplateResolveSource,
    TemplateResolveStatus,
    WorkflowTemplateEligibility,
    WorkflowTemplateRequest,
    WorkflowTemplateResolution,
    WorkflowTemplateSpec,
)
from app.director.workflows.registry import WorkflowTemplateRegistry


class WorkflowTemplateResolver:
    """Resolve a template for a shot/scene intent, provider-neutral."""

    def __init__(self, registry: WorkflowTemplateRegistry) -> None:
        self._registry = registry

    def resolve(self, request: WorkflowTemplateRequest) -> WorkflowTemplateResolution:
        if request.explicit_template_key:
            return self._resolve_explicit(request)
        return self._resolve_auto(request)

    def _resolve_explicit(
        self, request: WorkflowTemplateRequest
    ) -> WorkflowTemplateResolution:
        requested_key = request.explicit_template_key
        if requested_key is None:
            return self._unavailable(
                request,
                "no explicit template requested",
                source=TemplateResolveSource.EXPLICIT,
            )
        spec = self._registry.get(requested_key)
        if spec is None:
            return self._unavailable(
                request,
                f"template {request.explicit_template_key!r} is not registered",
                source=TemplateResolveSource.EXPLICIT,
            )
        eligibility = self._registry.evaluate(spec, request)
        if not eligibility.eligible:
            return WorkflowTemplateResolution(
                requested_template_key=request.explicit_template_key,
                resolved_template_key=None,
                template_version=spec.template_version,
                status=TemplateResolveStatus.UNAVAILABLE,
                source=TemplateResolveSource.EXPLICIT,
                reason="; ".join(eligibility.reasons) or "template is ineligible",
                contract_hash=spec.contract_hash,
                eligibility=eligibility,
            )
        return WorkflowTemplateResolution(
            requested_template_key=request.explicit_template_key,
            resolved_template_key=spec.template_key,
            template_version=spec.template_version,
            status=TemplateResolveStatus.RESOLVED,
            source=TemplateResolveSource.EXPLICIT,
            reason=None,
            contract_hash=spec.contract_hash,
            eligibility=eligibility,
        )

    def _resolve_auto(self, request: WorkflowTemplateRequest) -> WorkflowTemplateResolution:
        candidates = self._registry.eligible(request)
        if not candidates:
            return self._unavailable(
                request, "no registered template is eligible", source=TemplateResolveSource.AUTO
            )
        # Prefer the template that matches the most intent tags (deterministic).
        best: WorkflowTemplateSpec
        best_eligibility: WorkflowTemplateEligibility
        best, best_eligibility = max(
            candidates,
            key=lambda pair: (
                len(pair[1].matched_intent_tags),
                pair[0].template_key,
            ),
        )
        return WorkflowTemplateResolution(
            requested_template_key=None,
            resolved_template_key=best.template_key,
            template_version=best.template_version,
            status=TemplateResolveStatus.RESOLVED,
            source=TemplateResolveSource.AUTO,
            reason=None,
            contract_hash=best.contract_hash,
            eligibility=best_eligibility,
        )

    def _unavailable(
        self,
        request: WorkflowTemplateRequest,
        reason: str,
        *,
        source: TemplateResolveSource,
    ) -> WorkflowTemplateResolution:
        eligibility = WorkflowTemplateEligibility(
            template_key=request.explicit_template_key or "",
            eligible=False,
            reasons=[reason],
        )
        return WorkflowTemplateResolution(
            requested_template_key=request.explicit_template_key,
            resolved_template_key=None,
            template_version=None,
            status=TemplateResolveStatus.UNAVAILABLE,
            source=source,
            reason=reason,
            contract_hash=None,
            eligibility=eligibility,
        )
