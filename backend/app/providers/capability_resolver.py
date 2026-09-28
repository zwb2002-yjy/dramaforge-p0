"""Pure, fail-closed matching of creative inputs to a model input contract.

Provider truth comes from one versioned ``ModelCapabilityManifest``. Product
policy restricts that truth without rewriting it. Account and binding gates
remain separate because they depend on the selected workspace connection.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from fnmatch import fnmatch
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.providers.errors import ProviderError
from app.providers.intents import ImageGenerationIntent, VideoGenerationIntentV1
from app.providers.manifest import (
    ConstraintSpec,
    InputContractSpec,
    InputSlotSpec,
    ModelCapabilityManifest,
    OperationManifest,
    ParameterSpec,
)
from app.providers.reference_roles import canonical_reference_role
from app.providers.validator import validate_parameter


class ReferenceMetadata(BaseModel):
    """Trusted artifact metadata resolved before a paid Provider submission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    mime_type: str = Field(min_length=1)
    byte_size: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class ProductCapabilityPolicy(BaseModel):
    """The subset of documented input contracts opened by this product path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_contracts: frozenset[str]
    allowed_options: frozenset[str] | None = None


class ResolvedGenerationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_type: str
    protocol_profile: str
    model_id: str
    model_revision: str
    operation: str
    matched_contract: str
    reference_ids: tuple[UUID, ...]
    reference_roles: tuple[str, ...]
    effective_options: dict[str, Any]


class CapabilityResolutionError(ValueError):
    def __init__(self, code: str, message: str, *, reasons: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reasons = reasons or {}


def _requested_inputs(
    intent: ImageGenerationIntent | VideoGenerationIntentV1,
) -> tuple[list[tuple[UUID, str]], dict[str, Any]]:
    if isinstance(intent, ImageGenerationIntent):
        references = (
            [(intent.reference_artifact_id, "reference_image")]
            if intent.reference_artifact_id is not None
            else []
        )
        options = {
            "size": intent.size,
            "aspect_ratio": intent.aspect_ratio,
            "seed": intent.seed,
        }
    else:
        references = []
        for reference in intent.references:
            role = canonical_reference_role(str(reference.role))
            if role is None:
                raise CapabilityResolutionError(
                    "INPUT_ROLE_UNKNOWN", f"unknown reference role: {reference.role}"
                )
            references.append((reference.artifact_id, role))
        options = intent.output.model_dump()
    return references, {name: value for name, value in options.items() if value is not None}


def _metadata_for(
    references: list[tuple[UUID, str]], metadata: list[ReferenceMetadata]
) -> list[tuple[str, ReferenceMetadata]]:
    by_id = {item.artifact_id: item for item in metadata}
    if len(by_id) != len(metadata) or {item[0] for item in references} != set(by_id):
        raise CapabilityResolutionError(
            "REFERENCE_METADATA_MISMATCH", "reference metadata does not match selected artifacts"
        )
    return [(role, by_id[artifact_id]) for artifact_id, role in references]


def _check_slot(slot: InputSlotSpec, role: str, item: ReferenceMetadata) -> None:
    if slot.media_types and not any(
        fnmatch(item.mime_type.lower(), pattern.lower()) for pattern in slot.media_types
    ):
        raise ValueError(f"{role} does not accept {item.mime_type}")
    for name, value, bound in (
        ("byte size", item.byte_size, slot.max_bytes),
        ("duration", item.duration_seconds, slot.max_duration_seconds),
        ("width", item.width, slot.max_width),
        ("height", item.height, slot.max_height),
    ):
        if bound is not None and (value is None or value > bound):
            raise ValueError(f"{role} {name} exceeds or lacks a declared limit")
    for name, value, bound in (
        ("duration", item.duration_seconds, slot.min_duration_seconds),
        ("width", item.width, slot.min_width),
        ("height", item.height, slot.min_height),
    ):
        if bound is not None and (value is None or value < bound):
            raise ValueError(f"{role} {name} is below or lacks a declared minimum")


def _check_constraints(values: dict[str, Any], constraints: ConstraintSpec) -> None:
    for group in constraints.mutually_exclusive:
        if sum(values.get(name) is not None for name in group) > 1:
            raise ValueError(f"mutually exclusive options: {group}")
    for name, required in constraints.requires.items():
        if values.get(name) is not None and any(values.get(item) is None for item in required):
            raise ValueError(f"{name} requires {required}")
    for condition in constraints.conditional:
        if not all(values.get(name) == value for name, value in condition.when.items()):
            continue
        if any(values.get(name) is None for name in condition.require):
            raise ValueError(f"conditional options require {condition.require}")
        if any(values.get(name) is not None for name in condition.forbid):
            raise ValueError(f"conditional options forbid {condition.forbid}")
        for name, allowed in condition.allowed.items():
            if values.get(name) is not None and values[name] not in allowed:
                raise ValueError(f"{name} is not allowed for this option combination")


def _check_contract(
    contract: InputContractSpec,
    operation: OperationManifest,
    references: list[tuple[str, ReferenceMetadata]],
    options: dict[str, Any],
) -> dict[str, Any]:
    counts = Counter(role for role, _ in references)
    total = len(references)
    if total < contract.minimum_total_references:
        raise ValueError("too few references for this contract")
    if contract.maximum_total_references is not None and total > contract.maximum_total_references:
        raise ValueError("too many references for this contract")
    for role, count in counts.items():
        slot = contract.input_slots.get(role)
        if slot is None:
            raise ValueError(f"undeclared reference slot: {role}")
        if slot.maximum is not None and count > slot.maximum:
            raise ValueError(f"too many {role} references")
    for role, slot in contract.input_slots.items():
        if counts.get(role, 0) < max(slot.minimum, int(slot.required)):
            raise ValueError(f"required reference slot is missing: {role}")
    durations: dict[str, float] = defaultdict(float)
    for role, item in references:
        _check_slot(contract.input_slots[role], role, item)
        if role in contract.max_total_duration_seconds:
            if item.duration_seconds is None:
                raise ValueError(f"{role} duration metadata is missing")
            durations[role] += item.duration_seconds
    for role, limit in contract.max_total_duration_seconds.items():
        if durations[role] > limit:
            raise ValueError(f"aggregate {role} duration exceeds {limit}s")

    declared: dict[str, ParameterSpec] = {
        **operation.output_options,
        **contract.common_options,
        **contract.native_options,
    }
    effective: dict[str, Any] = {}
    for name, spec in declared.items():
        if spec.default is not None:
            try:
                validate_parameter(name, spec.default, spec)
            except ProviderError as exc:
                raise ValueError(f"invalid manifest default for {name}: {exc}") from exc
            effective[name] = spec.default
    for name, value in options.items():
        requested_spec = declared.get(name)
        if requested_spec is None:
            raise ValueError(f"undeclared output option: {name}")
        try:
            validate_parameter(name, value, requested_spec)
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
        effective[name] = value
    for name, spec in declared.items():
        if spec.required and name not in effective:
            raise ValueError(f"required output option is missing: {name}")
    _check_constraints(effective, contract.constraints)
    return effective


class CapabilityResolver:
    def resolve(
        self,
        *,
        manifest: ModelCapabilityManifest,
        intent: ImageGenerationIntent | VideoGenerationIntentV1,
        reference_metadata: list[ReferenceMetadata],
        policy: ProductCapabilityPolicy,
    ) -> ResolvedGenerationPlan:
        if not intent.prompt.strip():
            raise CapabilityResolutionError("PROMPT_REQUIRED", "prompt is required")
        if manifest.lifecycle == "retired":
            raise CapabilityResolutionError("MODEL_RETIRED", "model is retired")
        operation_name = intent.operation
        operation = manifest.operations.get(operation_name)
        if operation is None:
            raise CapabilityResolutionError("OPERATION_UNSUPPORTED", operation_name)
        if not operation.input_contracts:
            raise CapabilityResolutionError(
                "INPUT_CONTRACT_NOT_DECLARED", "model revision has no input contracts"
            )
        selected, options = _requested_inputs(intent)
        references = _metadata_for(selected, reference_metadata)
        matches: list[tuple[str, dict[str, Any]]] = []
        reasons: dict[str, str] = {}
        for contract_id, contract in operation.input_contracts.items():
            try:
                effective = _check_contract(contract, operation, references, options)
            except ValueError as exc:
                reasons[contract_id] = str(exc)
            else:
                matches.append((contract_id, effective))
        if not matches:
            raise CapabilityResolutionError(
                "MODEL_INPUT_COMBINATION_UNSUPPORTED",
                "no input contract accepts this request",
                reasons=reasons,
            )
        if len(matches) != 1:
            raise CapabilityResolutionError(
                "MANIFEST_CONTRACT_AMBIGUOUS",
                "multiple input contracts accept this request",
            )
        contract_id, effective = matches[0]
        if contract_id not in policy.allowed_contracts:
            raise CapabilityResolutionError(
                "PRODUCT_CAPABILITY_CLOSED", f"product policy does not open {contract_id}"
            )
        if policy.allowed_options is not None and not options.keys() <= policy.allowed_options:
            raise CapabilityResolutionError(
                "PRODUCT_OPTION_CLOSED", "product policy does not open a requested option"
            )
        return ResolvedGenerationPlan(
            provider_type=manifest.provider_type,
            protocol_profile=manifest.protocol_profile,
            model_id=manifest.model_id,
            model_revision=manifest.model_revision,
            operation=operation_name,
            matched_contract=contract_id,
            reference_ids=tuple(artifact_id for artifact_id, _ in selected),
            reference_roles=tuple(role for _, role in selected),
            effective_options=effective,
        )
