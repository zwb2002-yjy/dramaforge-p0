"""Typed capability facts on the same Catalog, with explicit unknown bounds.

Legacy JSON remains frozen and uses its original reader. This version contains
knowledge; declaring an operation never registers a Compiler or Runtime.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

from pydantic import Field, JsonValue, StrictFloat, StrictInt, model_validator

from app.providers.source_evidence import ClaimStatus, EvidenceModel, EvidenceReview, SourceScope

TypedOperationKind = Literal[
    "image.generate",
    "image.edit",
    "image.extend",
    "image.layer_decomposition",
    "image.interactive_edit",
    "video.generate",
    "video.edit",
    "video.extend",
]


class CapabilityBound(EvidenceModel):
    kind: Literal["bounded", "unlimited", "unknown"]
    value: StrictInt | StrictFloat | None = None
    claim_status: ClaimStatus = "unknown"
    inclusive: bool = True

    @model_validator(mode="after")
    def validate_bound(self) -> CapabilityBound:
        if self.kind == "bounded":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("bounded capability requires a finite value")
        elif self.value is not None:
            raise ValueError("unknown/unlimited bounds have no numeric value")
        if self.kind == "unknown" and self.claim_status == "documented_supported":
            raise ValueError("an unknown limit cannot be declared supported")
        if self.kind == "unlimited" and self.claim_status != "documented_supported":
            raise ValueError("unlimited requires an explicit supported declaration")
        return self

    def upper_value(self) -> int | float | None:
        if self.kind == "unknown" or self.claim_status != "documented_supported":
            raise ValueError("CAPABILITY_BOUND_UNKNOWN_OR_UNSUPPORTED")
        return self.value


def unknown_bound() -> CapabilityBound:
    return CapabilityBound(kind="unknown")


class TypedParameter(EvidenceModel):
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    claim_status: ClaimStatus = "unknown"
    control: Literal["native", "derived", "prompt_only", "unsupported", "unknown"] = "unknown"
    required: bool | None = None
    wire_name: str | None = None
    multiple_of: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    enum: tuple[JsonValue, ...] = ()
    minimum: CapabilityBound = Field(default_factory=unknown_bound)
    maximum: CapabilityBound = Field(default_factory=unknown_bound)
    min_items: CapabilityBound = Field(default_factory=unknown_bound)
    max_items: CapabilityBound = Field(default_factory=unknown_bound)
    min_length: CapabilityBound = Field(default_factory=unknown_bound)
    max_length: CapabilityBound = Field(default_factory=unknown_bound)
    # Structured alternative to a named size tier; unknown limits remain explicit.
    dimension_bounds: dict[str, CapabilityBound] = Field(default_factory=dict)
    default: JsonValue = None
    default_status: ClaimStatus = "unknown"
    evidence_group_ref: str | None = None
    evidence_review: EvidenceReview | None = None

    @model_validator(mode="after")
    def validate_parameter(self) -> TypedParameter:
        for lower, upper in ((self.minimum, self.maximum), (self.min_items, self.max_items)):
            if (
                lower.kind == upper.kind == "bounded"
                and lower.value is not None
                and upper.value is not None
                and lower.value > upper.value
            ):
                raise ValueError("parameter minimum exceeds maximum")
        if (
            self.enum
            and self.default_status == "documented_supported"
            and self.default not in self.enum
        ):
            raise ValueError("documented default is outside parameter enum")
        values = [*self.enum]
        if self.default_status == "documented_supported":
            values.append(self.default)
        if any(not _parameter_type_matches(value, self.type) for value in values):
            raise ValueError("parameter enum/default does not match its declared type")
        return self


def _parameter_type_matches(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    return isinstance(value, {"string": str, "boolean": bool, "array": list, "object": dict}[kind])


class TypedInputSlot(EvidenceModel):
    claim_status: ClaimStatus = "unknown"
    required: bool = False
    minimum: CapabilityBound = Field(default_factory=unknown_bound)
    maximum: CapabilityBound = Field(default_factory=unknown_bound)
    media_types: tuple[str, ...] = ()
    codecs: tuple[str, ...] = ()
    aspect_ratios: tuple[str, ...] = ()
    ordering: Literal["preserve", "unknown"] = "unknown"
    wire_field: str | None = None
    delivery_formats: tuple[str, ...] = ()
    wire_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    wire_options: dict[str, TypedParameter] = Field(default_factory=dict)
    max_bytes: CapabilityBound = Field(default_factory=unknown_bound)
    min_duration_seconds: CapabilityBound = Field(default_factory=unknown_bound)
    max_duration_seconds: CapabilityBound = Field(default_factory=unknown_bound)
    min_width: CapabilityBound = Field(default_factory=unknown_bound)
    max_width: CapabilityBound = Field(default_factory=unknown_bound)
    min_height: CapabilityBound = Field(default_factory=unknown_bound)
    max_height: CapabilityBound = Field(default_factory=unknown_bound)
    min_fps: CapabilityBound = Field(default_factory=unknown_bound)
    max_fps: CapabilityBound = Field(default_factory=unknown_bound)
    min_pixels: CapabilityBound = Field(default_factory=unknown_bound)
    max_pixels: CapabilityBound = Field(default_factory=unknown_bound)
    min_aspect_ratio: CapabilityBound = Field(default_factory=unknown_bound)
    max_aspect_ratio: CapabilityBound = Field(default_factory=unknown_bound)
    evidence_group_ref: str | None = None
    evidence_review: EvidenceReview | None = None

    @model_validator(mode="after")
    def validate_slot(self) -> TypedInputSlot:
        if any(
            isinstance(value, CapabilityBound) and value.value is not None and value.value < 0
            for _name, value in self
        ):
            raise ValueError("input media bounds cannot be negative")
        if self.maximum.kind == "bounded" and (
            not isinstance(self.maximum.value, int)
            or (
                self.minimum.kind == "bounded"
                and self.minimum.value is not None
                and self.maximum.value < self.minimum.value
            )
        ):
            raise ValueError("input cardinality requires an integer maximum above minimum")
        if self.minimum.kind == "bounded" and not isinstance(self.minimum.value, int):
            raise ValueError("input minimum cardinality requires an integer")
        if self.minimum.kind == "unlimited":
            raise ValueError("input minimum cannot be unlimited")
        if (
            self.required
            and self.minimum.kind == "bounded"
            and self.minimum.value is not None
            and self.minimum.value < 1
        ):
            raise ValueError("required input slot must declare minimum at least one")
        import re

        if any(not re.fullmatch(r"[1-9]\d*:[1-9]\d*", ratio) for ratio in self.aspect_ratios):
            raise ValueError("input aspect ratios must have positive integer terms")
        for lower, upper in (
            (self.min_duration_seconds, self.max_duration_seconds),
            (self.min_width, self.max_width),
            (self.min_height, self.max_height),
            (self.min_fps, self.max_fps),
        ):
            if (
                lower.kind == upper.kind == "bounded"
                and lower.value is not None
                and upper.value is not None
                and lower.value > upper.value
            ):
                raise ValueError("input media minimum exceeds maximum")
        return self


class TypedConstraint(EvidenceModel):
    kind: Literal[
        "requires", "requires_any", "exclusion", "conditional", "derived", "forced", "sum_limit"
    ]
    claim_status: ClaimStatus = "unknown"
    when: dict[str, JsonValue] = Field(default_factory=dict)
    when_present: tuple[str, ...] = ()
    require: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    allowed: dict[str, tuple[JsonValue, ...]] = Field(default_factory=dict)
    target: str | None = None
    value: JsonValue = None
    derivation: Literal["reference_count", "reference_duration_sum"] | None = None
    description: str = ""
    sum_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_rule(self) -> TypedConstraint:
        if self.kind in {"derived", "forced"} and self.target is None:
            raise ValueError("derived/forced rules require an explicit target")
        if self.kind == "derived" and self.derivation is None:
            raise ValueError("derived rules require a supported derivation")
        if self.kind in {"requires", "requires_any"} and not self.require:
            raise ValueError("requires rule is empty")
        if self.kind == "exclusion" and not self.forbid:
            raise ValueError("exclusion rule is empty")
        if self.kind == "conditional" and not (self.allowed or self.require or self.forbid):
            raise ValueError("conditional rule is empty")
        if self.kind == "sum_limit" and (
            not self.sum_fields or not isinstance(self.value, (int, float))
        ):
            raise ValueError("sum limit requires declared fields and a numeric maximum")
        return self


class TypedInputContract(EvidenceModel):
    claim_status: ClaimStatus = "unknown"
    input_slots: dict[str, TypedInputSlot] = Field(default_factory=dict)
    output_options: dict[str, TypedParameter] = Field(default_factory=dict)
    minimum_total_references: CapabilityBound = Field(default_factory=unknown_bound)
    maximum_total_references: CapabilityBound = Field(default_factory=unknown_bound)
    max_total_duration_seconds: dict[str, CapabilityBound] = Field(default_factory=dict)
    min_total_duration_seconds: dict[str, CapabilityBound] = Field(default_factory=dict)
    maximum_total_bytes: CapabilityBound = Field(default_factory=unknown_bound)
    max_total_bytes_by_role: dict[str, CapabilityBound] = Field(default_factory=dict)
    constraints: tuple[TypedConstraint, ...] = ()
    evidence_group_ref: str | None = None
    evidence_review: EvidenceReview | None = None

    @model_validator(mode="after")
    def validate_aggregate(self) -> TypedInputContract:
        if any(
            bound.value is not None and bound.value < 0
            for bound in (
                self.minimum_total_references,
                self.maximum_total_references,
                self.maximum_total_bytes,
                *self.max_total_duration_seconds.values(),
                *self.min_total_duration_seconds.values(),
                *self.max_total_bytes_by_role.values(),
            )
        ):
            raise ValueError("input aggregate bounds cannot be negative")
        limit = self.maximum_total_references
        if limit.kind == "bounded" and (
            not isinstance(limit.value, int)
            or (
                self.minimum_total_references.kind == "bounded"
                and self.minimum_total_references.value is not None
                and limit.value < self.minimum_total_references.value
            )
        ):
            raise ValueError("total reference maximum must be an integer above minimum")
        if self.minimum_total_references.kind == "unlimited" or (
            self.minimum_total_references.kind == "bounded"
            and not isinstance(self.minimum_total_references.value, int)
        ):
            raise ValueError("total reference minimum must be unknown or a bounded integer")
        if any(role not in self.input_slots for role in self.max_total_duration_seconds):
            raise ValueError("aggregate duration must reference a declared input role")
        return self


class EvidenceOverride(EvidenceModel):
    claim_status: ClaimStatus
    source_snapshot_ref: str
    evidence_review: EvidenceReview
    issue: str = ""


class TypedOperation(EvidenceModel):
    operation: TypedOperationKind
    claim_status: ClaimStatus = "unknown"
    input_contracts: dict[str, TypedInputContract] = Field(default_factory=dict)
    output_options: dict[str, TypedParameter] = Field(default_factory=dict)
    constraints: tuple[TypedConstraint, ...] = ()
    maximum_request_bytes: CapabilityBound = Field(default_factory=unknown_bound)
    # Protocol observations are knowledge; the immutable TransportProfile still
    # owns execution and decoding. These facts do not create another runtime.
    protocol_facts: dict[str, TypedParameter] = Field(default_factory=dict)
    prompt_spec: TypedParameter | None = None
    evidence_group_ref: str | None = None
    evidence_review: EvidenceReview | None = None
    evidence_overrides: dict[str, EvidenceOverride] = Field(default_factory=dict)


class TypedModelCapabilityManifest(EvidenceModel):
    schema_version: Literal["2"]
    manifest_version: str
    provider_type: str
    protocol_profile: str
    api_version: str = "unknown"
    region: str = "unknown"
    model_id: str
    model_revision: str
    media_kind: Literal["image", "video"]
    display_name: str
    lifecycle: Literal["preview", "active", "legacy", "deprecated", "retired"] = "preview"
    catalog_source: Literal["official_static", "protocol_contract"] = "official_static"
    documented_at: date
    operations: dict[TypedOperationKind, TypedOperation]
    # Identity of the frozen inventory entry being refined, never an execution fallback.
    refines_revision: str | None = None

    @model_validator(mode="after")
    def validate_operations(self) -> TypedModelCapabilityManifest:
        if not self.operations:
            raise ValueError("typed capability manifest must declare at least one operation")
        for key, operation in self.operations.items():
            if key != operation.operation:
                raise ValueError("operation key does not match declared operation")
            if not key.startswith(self.media_kind + "."):
                raise ValueError("operation media does not match model media kind")
            for contract in operation.input_contracts.values():
                for role in contract.input_slots:
                    from app.providers.reference_roles import canonical_reference_role

                    if role not in {"source_image", "source_video"} and (
                        canonical_reference_role(role) != role
                    ):
                        raise ValueError("typed input roles must be canonical")
        return self

    def source_scope(self) -> SourceScope:
        return SourceScope(
            provider_type=self.provider_type,
            protocol_profile=self.protocol_profile,
            model_id=self.model_id,
            api_version=self.api_version,
            region=self.region,
        )
