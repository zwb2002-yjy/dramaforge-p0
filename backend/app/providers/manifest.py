"""Model capability manifest types (pure Pydantic, no ORM / Settings deps).

A :class:`ModelCapabilityManifest` is the versioned capability contract for one
concrete model (``provider_type + protocol_profile + model_id + model_revision``).
It is the "model ability layer" of the three-layer split: creative intent ->
model capability -> wire compilation. Manifests are immutable; a model contract
change adds a new revision row instead of mutating an existing one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

from app.providers.capabilities import Capability
from app.providers.reference_roles import ROLE_MEDIA_TYPES, canonical_reference_role

ManifestVersion = str
MediaKind = Literal["image", "video", "text", "voice"]
Lifecycle = Literal["preview", "active", "deprecated", "retired"]
CatalogSource = Literal["official_static", "account_discovery", "admin_approved"]
OperationKind = Literal["image.generate", "video.generate"]


class OptionSpec(BaseModel):
    """One validated native option in a model's option schema."""

    type: Literal["enum", "boolean", "integer", "number", "string"]
    values: list[JsonValue] | None = None
    default: JsonValue | None = None
    minimum: float | None = None
    maximum: float | None = None


class ModelOptionSchema(BaseModel):
    """Namespaced whitelist of native advanced options a compiler accepts."""

    namespace: str
    options: dict[str, OptionSpec] = Field(default_factory=dict)


class ReferenceConstraint(BaseModel):
    """Per-role artifact reference cardinality. Absent roles are forbidden."""

    min: int = 0
    max: int = 0


class ExclusiveGroup(BaseModel):
    """Mutually exclusive reference-role groups, e.g. frame endpoints vs
    multimodal references. ``members`` is a list of role-name lists; at most one
    member list may be non-empty in a single request."""

    name: str
    members: list[list[str]]


class OperationManifest(BaseModel):
    """Capability contract for one operation (image.generate / video.generate)."""

    operation: OperationKind
    capabilities: list[str]
    output_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    reference_constraints: dict[str, ReferenceConstraint] = Field(default_factory=dict)
    exclusive_groups: list[ExclusiveGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_reference_constraints(self) -> OperationManifest:
        normalized: dict[str, ReferenceConstraint] = {}
        for role, constraint in self.reference_constraints.items():
            normalized_role = canonical_reference_role(role) or role
            if normalized_role in normalized and normalized[normalized_role] != constraint:
                raise ValueError(f"duplicate reference role aliases: {normalized_role}")
            normalized[normalized_role] = constraint
        self.reference_constraints = normalized
        for group in self.exclusive_groups:
            group.members = [
                [canonical_reference_role(role) or role for role in member]
                for member in group.members
            ]
        return self

    def reference_role_capability(self, role: str) -> str | None:
        """Map an artifact reference role to its canonical capability name."""
        canonical_role = canonical_reference_role(role) or role
        return {
            "first_frame": "video.i2v.first_frame",
            "last_frame": "video.i2v.last_frame",
            "reference_image": "video.reference.image",
            "reference_video": "video.reference.video",
            "reference_audio": "video.reference.audio",
        }.get(canonical_role)


class ModelCapabilityManifest(BaseModel):
    """Versioned capability manifest for one concrete model."""

    manifest_version: str
    provider_type: str
    protocol_profile: str
    model_id: str
    model_revision: str
    media_kind: MediaKind
    display_name: str
    lifecycle: Lifecycle = "active"
    catalog_source: CatalogSource = "official_static"
    documented_at: date
    operations: dict[OperationKind, OperationManifest]
    option_schema: ModelOptionSchema = Field(
        default_factory=lambda: ModelOptionSchema(namespace="")
    )


# ---------------------------------------------------------------------------
# V3 capability-spec types (spec §14–§18, additive).
# These express *what one model supports for one capability*: input slots,
# common/native options with schemas, and cross-field constraints. They are the
# contract that drives the frontend manifest UI and the strict validator.
# ---------------------------------------------------------------------------

ParameterType = Literal["string", "integer", "number", "boolean", "array", "object"]


class InputSlotSpec(BaseModel):
    """One artifact input role for a capability (spec §15). Absent roles are
    forbidden. ``minimum``/``maximum`` bound the number of artifacts accepted."""

    required: bool = False
    minimum: int = 0
    maximum: int | None = None
    media_types: list[str] = Field(default_factory=list)
    description: str | None = None


def _canonicalize_input_slot_map(
    input_slots: dict[str, InputSlotSpec],
) -> dict[str, InputSlotSpec]:
    normalized: dict[str, InputSlotSpec] = {}
    for role, slot in input_slots.items():
        normalized_role = canonical_reference_role(role) or role
        if normalized_role in normalized and normalized[normalized_role] != slot:
            raise ValueError(f"duplicate input slot aliases: {normalized_role}")
        normalized[normalized_role] = slot
    return normalized


class ParameterSpec(BaseModel):
    """One validated option (common or native) in a capability (spec §16)."""

    type: ParameterType
    title: str | None = None
    description: str | None = None
    required: bool = False
    default: Any | None = None
    enum: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None
    max_items: int | None = None
    ui_component: Literal[
        "switch",
        "select",
        "number",
        "slider",
        "input",
        "textarea",
        "multi_select",
    ] | None = None
    deprecated: bool = False
    sensitive: bool = False


class ConditionalConstraint(BaseModel):
    """When ``when`` matches, ``require`` must be present, ``forbid`` must be
    absent, and any key in ``allowed`` must take one of the listed values
    (spec §17). E.g. ``when={"duration_seconds": 10}`` + ``allowed={
    "resolution": ["720p"]}`` expresses a duration-resolution matrix (§18)."""

    when: dict[str, Any]
    require: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)
    allowed: dict[str, list[Any]] = Field(default_factory=dict)


class ConstraintSpec(BaseModel):
    """Cross-field constraint set for one capability (spec §17/§18)."""

    mutually_exclusive: list[list[str]] = Field(default_factory=list)
    requires: dict[str, list[str]] = Field(default_factory=dict)
    conditional: list[ConditionalConstraint] = Field(default_factory=list)


class InputModeSpec(BaseModel):
    """Mode-specific input contract inside one capability (MS4-LITE)."""

    id: str
    title: str
    description: str | None = None
    input_slots: dict[str, InputSlotSpec] = Field(default_factory=dict)
    common_options: dict[str, ParameterSpec] = Field(default_factory=dict)
    native_options: dict[str, ParameterSpec] = Field(default_factory=dict)
    constraints: ConstraintSpec = Field(default_factory=ConstraintSpec)

    @model_validator(mode="after")
    def canonicalize_input_slots(self) -> InputModeSpec:
        self.input_slots = _canonicalize_input_slot_map(self.input_slots)
        return self


class CapabilitySpec(BaseModel):
    """What one concrete model supports for one capability (spec §14)."""

    capability: Capability
    input_slots: dict[str, InputSlotSpec] = Field(default_factory=dict)
    common_options: dict[str, ParameterSpec] = Field(default_factory=dict)
    native_options: dict[str, ParameterSpec] = Field(default_factory=dict)
    constraints: ConstraintSpec = Field(default_factory=ConstraintSpec)
    modes: dict[str, InputModeSpec] = Field(default_factory=dict)
    default_mode: str | None = None
    transport_profile_id: str

    @model_validator(mode="after")
    def canonicalize_input_slots(self) -> CapabilitySpec:
        self.input_slots = _canonicalize_input_slot_map(self.input_slots)
        if self.default_mode is not None and self.default_mode not in self.modes:
            raise ValueError(f"default mode is not declared: {self.default_mode}")
        return self

    def mode_spec(self, mode_id: str | None = None) -> InputModeSpec:
        """Return the selected mode, or the additive legacy contract."""
        if not self.modes:
            return InputModeSpec(
                id=mode_id or "legacy",
                title="Legacy capability contract",
                input_slots=self.input_slots,
                common_options=self.common_options,
                native_options=self.native_options,
                constraints=self.constraints,
            )
        selected = mode_id or self.default_mode
        if selected is None:
            raise ValueError("mode_id is required")
        mode = self.modes.get(selected)
        if mode is None:
            raise ValueError(f"mode is not declared: {selected}")
        return mode


class SubmissionSemantics(BaseModel):
    """Per-model idempotency/submission declaration (spec §49). Never inferred;
    only set from officially documented provider behavior."""

    provider_idempotency_supported: bool = False
    idempotency_location: Literal["header", "body", "none"] = "none"
    idempotency_name: str | None = None
    client_request_id_supported: bool = False
    lookup_by_client_request_id: bool = False


class ModelManifest(BaseModel):
    """V3 model manifest (spec §20). Describes capabilities only — it never
    performs HTTP, holds keys, uploads files, or writes DB rows."""

    schema_version: str = "1"
    manifest_version: str
    id: str
    provider_id: str
    model_name: str
    display_name: str
    model_family: str | None = None
    capability_specs: dict[Capability, CapabilitySpec]
    execution_mode: Literal["sync", "async_poll", "async_webhook"]
    supports_cancel: bool = False
    submission_semantics: SubmissionSemantics
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Bridge from the A+B capability manifest to the V3 manifest shape.
# The A+B engine stays the runtime authority; this pure converter produces the
# V3 view used by the CapabilityRouter validator and the frontend manifest API.
# ---------------------------------------------------------------------------

_ROLE_MEDIA_TYPES = ROLE_MEDIA_TYPES

_EXECUTION_MODE_BY_KIND: dict[MediaKind, Literal["sync", "async_poll"]] = {
    "image": "sync",
    "video": "async_poll",
    "text": "sync",
    "voice": "sync",
}


_PARAMETER_TYPE_MAP: dict[str, ParameterType] = {
    "boolean": "boolean",
    "integer": "integer",
    "number": "number",
    "string": "string",
}


def _option_spec_to_parameter(spec: OptionSpec, *, required: bool = False) -> ParameterSpec:
    """Best-effort OptionSpec → V3 ParameterSpec."""
    if spec.type == "enum" and spec.values:
        return ParameterSpec(
            type="string",
            title=spec.type,
            default=spec.default,
            enum=[value for value in spec.values if value is not None],
            required=required,
        )
    return ParameterSpec(
        type=_PARAMETER_TYPE_MAP.get(spec.type, "string"),
        default=spec.default,
        minimum=spec.minimum,
        maximum=spec.maximum,
        required=required,
    )


_PY_TYPE_TO_PARAMETER_TYPE: dict[type, ParameterType] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def _output_constraint_to_parameter(name: str, value: JsonValue) -> ParameterSpec | None:
    """Map an operation output constraint to a common option when it is a fixed
    or enumerated value the frontend can offer (e.g. num_frames allowed list,
    fixed size). Unknown shapes are ignored (strictness lives in the validator,
    not the manifest builder)."""
    if isinstance(value, dict):
        allowed = value.get("allowed")
        if isinstance(allowed, list) and allowed:
            return ParameterSpec(
                type="integer",
                enum=[item for item in allowed if item is not None],
            )
        return None
    if isinstance(value, int | float | str | bool):
        parameter_type = _PY_TYPE_TO_PARAMETER_TYPE.get(type(value), "string")
        return ParameterSpec(type=parameter_type, enum=[value])
    return None


def _v3_capabilities_for(operation: str, declared: set[str]) -> list[Capability]:
    """Derive the V3 coarse capabilities an A+B operation satisfies."""
    if operation == "image.generate":
        capabilities: list[Capability] = []
        if "image.t2i" in declared:
            capabilities.append(Capability.IMAGE_GENERATE)
        if "image.i2i" in declared:
            capabilities.append(Capability.IMAGE_GENERATE)
            capabilities.append(Capability.IMAGE_EDIT)
        return _dedupe(capabilities)
    if operation == "video.generate":
        capabilities = []
        if "video.t2v" in declared:
            capabilities.append(Capability.VIDEO_TEXT_TO_VIDEO)
        if "video.i2v" in declared or "video.i2v.first_frame" in declared:
            capabilities.append(Capability.VIDEO_IMAGE_TO_VIDEO)
        if "video.keyframes" in declared or (
            "video.i2v.first_frame" in declared and "video.i2v.last_frame" in declared
        ):
            capabilities.append(Capability.VIDEO_FIRST_LAST_FRAME)
        if any(
            member in declared
            for member in (
                "video.reference.image",
                "video.reference.video",
                "video.reference.audio",
            )
        ):
            capabilities.append(Capability.VIDEO_REFERENCE_TO_VIDEO)
        return _dedupe(capabilities)
    return []


def _dedupe(values: list[Capability]) -> list[Capability]:
    seen: set[Capability] = set()
    result: list[Capability] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _mode_id_for_roles(roles: list[str], index: int) -> str:
    role_set = frozenset(roles)
    if role_set == {"first_frame"}:
        return "first_frame"
    if role_set == {"first_frame", "last_frame"}:
        return "first_last_frame"
    if role_set & {"reference_image", "reference_video", "reference_audio"}:
        return "omni_reference"
    return f"mode_{index + 1}"


def _mode_title(mode_id: str) -> str:
    return {
        "text_to_video": "Text to video",
        "first_frame": "First frame",
        "first_last_frame": "First + last frame",
        "omni_reference": "Omni reference",
    }.get(mode_id, mode_id)


def _modes_from_operation(
    op_manifest: OperationManifest,
    *,
    input_slots: dict[str, InputSlotSpec],
    common_options: dict[str, ParameterSpec],
    native_options: dict[str, ParameterSpec],
) -> dict[str, InputModeSpec]:
    modes: dict[str, InputModeSpec] = {}
    for index, group in enumerate(op_manifest.exclusive_groups or []):
        for member in group.members:
            roles = [
                canonical_reference_role(role) or role
                for role in member
                if (canonical_reference_role(role) or role) in input_slots
            ]
            if not roles:
                continue
            mode_id = _mode_id_for_roles(roles, index)
            modes[mode_id] = InputModeSpec(
                id=mode_id,
                title=_mode_title(mode_id),
                description=f"Input mode from manifest group {group.name}",
                input_slots={role: input_slots[role] for role in roles},
                common_options=common_options,
                native_options=native_options,
                constraints=ConstraintSpec(),
            )
    return modes


def _capability_spec_for(
    operation: str,
    op_manifest: OperationManifest,
    capability: Capability,
    option_schema: ModelOptionSchema,
) -> CapabilitySpec:
    """Build one V3 CapabilitySpec from an A+B operation manifest."""
    input_slots: dict[str, InputSlotSpec] = {}
    for role, constraint in (op_manifest.reference_constraints or {}).items():
        canonical_role = canonical_reference_role(role) or role
        input_slots[canonical_role] = InputSlotSpec(
            required=constraint.min > 0,
            minimum=constraint.min,
            maximum=constraint.max if constraint.max > 0 else None,
            media_types=[_ROLE_MEDIA_TYPES[canonical_role]]
            if canonical_role in _ROLE_MEDIA_TYPES
            else [],
        )
    common_options: dict[str, ParameterSpec] = {}
    for name, value in (op_manifest.output_constraints or {}).items():
        parameter = _output_constraint_to_parameter(name, value)
        if parameter is not None:
            common_options[name] = parameter
    native_options: dict[str, ParameterSpec] = {}
    for name, spec in (option_schema.options or {}).items():
        native_options[name] = _option_spec_to_parameter(spec)
    modes = _modes_from_operation(
        op_manifest,
        input_slots=input_slots,
        common_options=common_options,
        native_options=native_options,
    )
    mutually_exclusive: list[list[str]] = []
    if not modes:
        for group in op_manifest.exclusive_groups or []:
            members = [member for item in group.members for member in item]
            mutually_exclusive.append(members)
    return CapabilitySpec(
        capability=capability,
        input_slots=input_slots,
        common_options=common_options,
        native_options=native_options,
        constraints=ConstraintSpec(mutually_exclusive=mutually_exclusive),
        modes=modes,
        default_mode=None,
        transport_profile_id="",
    )


def to_v3_model_manifest(
    manifest: ModelCapabilityManifest,
    *,
    transport_profile_id: str,
) -> ModelManifest:
    """Convert an A+B :class:`ModelCapabilityManifest` into the V3
    :class:`ModelManifest` view. The V3 id is ``<provider_type>/<model_id>``."""
    capability_specs: dict[Capability, CapabilitySpec] = {}
    declared_fine_grained: set[str] = set()
    for operation, op_manifest in (manifest.operations or {}).items():
        declared = set(op_manifest.capabilities)
        declared_fine_grained.update(declared)
        for capability in _v3_capabilities_for(operation, declared):
            spec = _capability_spec_for(
                operation,
                op_manifest,
                capability,
                manifest.option_schema,
            )
            spec.transport_profile_id = transport_profile_id
            capability_specs[capability] = spec
    execution_mode_value = _EXECUTION_MODE_BY_KIND.get(manifest.media_kind, "sync")
    return ModelManifest(
        manifest_version=manifest.manifest_version,
        id=f"{manifest.provider_type}/{manifest.model_id}",
        provider_id=manifest.provider_type,
        model_name=manifest.model_id,
        display_name=manifest.display_name,
        model_family=None,
        capability_specs=capability_specs,
        execution_mode=execution_mode_value,
        supports_cancel=False,
        submission_semantics=SubmissionSemantics(),
        metadata={
            "protocol_profile": manifest.protocol_profile,
            "model_revision": manifest.model_revision,
            "media_kind": manifest.media_kind,
            "lifecycle": manifest.lifecycle,
            "fine_grained_capabilities": sorted(declared_fine_grained),
        },
    )
