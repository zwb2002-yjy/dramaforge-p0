"""Shared model candidate eligibility engine (read-only, no side effects).

One implementation is used by both the model-candidates API and the runtime
``ModelSelectionService`` (stage B1), so the management view and the execution
resolver can never disagree about why a model is (not) eligible. Filters follow
design §9.1 order: binding enabled -> connection enabled -> documented +
contract_tested -> account_verified -> quality_gated -> required capabilities +
reference constraints -> exclusive groups -> preferred capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderConnection, ProviderModelBinding

# Capability names referenced by requirements/preferences.
IMAGE_GENERATE = "image.generate"
VIDEO_GENERATE = "video.generate"

_REFERENCE_ROLE_TO_CAPABILITY = {
    "first_frame": "video.i2v.first_frame",
    "last_frame": "video.i2v.last_frame",
    "reference_image": "video.reference.image",
    "reference_video": "video.reference.video",
    "reference_audio": "video.reference.audio",
}


@dataclass(frozen=True)
class EligibilityIssue:
    """Machine-readable reason a candidate is not eligible."""

    code: str
    detail: str


@dataclass(frozen=True)
class CandidateEvaluation:
    binding_id: UUID
    eligible: bool
    issues: list[EligibilityIssue] = field(default_factory=list)
    supported_capabilities: list[str] = field(default_factory=list)
    unmet_preferences: list[str] = field(default_factory=list)
    evidence: dict[str, bool] = field(default_factory=dict)
    estimated_cost: dict[str, Any] | None = None


def _issues_add(issues: list[EligibilityIssue], code: str, detail: str = "") -> None:
    issues.append(EligibilityIssue(code=code, detail=detail))


def _capability_satisfied(required: str, declared: set[str]) -> bool:
    """Exact capability match. Manifests declare the fine-grained capability
    they actually support (e.g. ``video.i2v.first_frame``), so a coarse
    declaration must NOT satisfy a sibling requirement such as
    ``video.i2v.last_frame``."""
    return required in declared


def _evidence_dict(binding: ProviderModelBinding) -> dict[str, bool]:
    return {
        "documented": binding.documented,
        "contract_tested": binding.contract_tested,
        "account_verified": binding.account_verified,
        "quality_gated": binding.quality_gated,
    }


def _early_ineligible(
    binding: ProviderModelBinding,
    issues: list[EligibilityIssue],
) -> CandidateEvaluation:
    return CandidateEvaluation(
        binding_id=binding.id,
        eligible=False,
        issues=issues,
        evidence=_evidence_dict(binding),
    )


async def evaluate_candidate(
    session: AsyncSession,
    *,
    binding: ProviderModelBinding,
    connection: ProviderConnection,
    catalog_entry: ModelCatalogEntry | None,
    operation: str,
    required_capabilities: frozenset[str] = frozenset(),
    reference_roles: frozenset[str] = frozenset(),
    preferred_capabilities: frozenset[str] = frozenset(),
) -> CandidateEvaluation:
    """Evaluate one model binding for one operation. Pure read; never calls a
    provider or writes anything."""
    issues: list[EligibilityIssue] = []

    if not binding.enabled:
        _issues_add(issues, "MODEL_BINDING_DISABLED", str(binding.id))
    if not connection.enabled:
        _issues_add(issues, "PROVIDER_CONNECTION_DISABLED", str(connection.id))
    if not binding.documented:
        _issues_add(issues, "MODEL_NOT_DOCUMENTED")
    if not binding.contract_tested:
        _issues_add(issues, "MODEL_NOT_CONTRACT_TESTED")
    if not binding.account_verified:
        _issues_add(issues, "MODEL_NOT_ACCOUNT_VERIFIED")
    if not binding.quality_gated:
        _issues_add(issues, "MODEL_QUALITY_GATE_MISSING")

    # Catalog snapshot consistency (review gate 8): the binding must reference an
    # active catalog revision of the same provider/profile/media with a complete
    # invoke value and a matching manifest hash.
    if binding.catalog_entry_id is None:
        _issues_add(issues, "MODEL_NOT_IN_CATALOG")
    if not binding.invoke_model_value:
        _issues_add(issues, "MODEL_NO_INVOKE_VALUE")
    if catalog_entry is None:
        _issues_add(issues, "MODEL_NOT_IN_CATALOG")
    else:
        if catalog_entry.lifecycle != "active":
            _issues_add(issues, "MODEL_LIFECYCLE_INACTIVE", catalog_entry.lifecycle)
        if (
            catalog_entry.provider_type != connection.provider_type
            or catalog_entry.protocol_profile != connection.protocol_profile
            or catalog_entry.media_kind != binding.media_type
        ):
            _issues_add(
                issues,
                "CATALOG_MISMATCH",
                f"{catalog_entry.provider_type}/{catalog_entry.protocol_profile}/"
                f"{catalog_entry.media_kind}",
            )
        if (
            binding.capability_manifest_hash
            and catalog_entry.contract_manifest_hash
            and binding.capability_manifest_hash != catalog_entry.contract_manifest_hash
        ):
            _issues_add(issues, "MANIFEST_HASH_MISMATCH")

    operations: dict[str, Any] = {}
    if catalog_entry is not None:
        operations = catalog_entry.capability_manifest_json.get("operations") or {}
    op = operations.get(operation) if isinstance(operations, dict) else None
    if op is None:
        _issues_add(issues, "CAPABILITY_REQUIRED_MISSING", operation)
        return _early_ineligible(binding, issues)

    capabilities = set(op.get("capabilities") or [])
    for capability in sorted(required_capabilities):
        if not _capability_satisfied(capability, capabilities):
            _issues_add(issues, "CAPABILITY_REQUIRED_MISSING", capability)
    reference_constraints = op.get("reference_constraints") or {}
    for role in sorted(reference_roles):
        constraint = reference_constraints.get(role)
        if constraint is None or int(constraint.get("max", 0)) < 1:
            _issues_add(issues, "CAPABILITY_REQUIRED_MISSING", f"reference role {role}")
    for group in op.get("exclusive_groups") or []:
        members = group.get("members") or []
        active_groups = [
            member for member in members if any(role in member for role in reference_roles)
        ]
        if len(active_groups) > 1:
            _issues_add(issues, "REFERENCE_MODE_CONFLICT", group.get("name", ""))

    unmet_preferences = sorted(
        capability
        for capability in preferred_capabilities
        if not _capability_satisfied(capability, capabilities)
    )
    supported_capabilities = sorted(capabilities)

    return CandidateEvaluation(
        binding_id=binding.id,
        eligible=not issues,
        issues=issues,
        supported_capabilities=supported_capabilities,
        unmet_preferences=unmet_preferences,
        evidence=_evidence_dict(binding),
        estimated_cost=None,
    )
