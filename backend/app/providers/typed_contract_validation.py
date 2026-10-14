"""Version-two validation used only through the sole CapabilityResolver.

This module interprets declarative facts. It cannot register a compiler, create
a binding, contact a provider, or turn a candidate into an executable contract.
"""

from __future__ import annotations

import math
from collections import Counter
from fnmatch import fnmatch
from typing import Any, cast
from uuid import UUID

from app.providers.capability_manifest_v2 import (
    CapabilityBound,
    TypedConstraint,
    TypedInputContract,
    TypedModelCapabilityManifest,
    TypedOperationKind,
    TypedParameter,
    _parameter_type_matches,
)
from app.providers.capability_resolver import (
    CapabilityResolutionError,
    ProductCapabilityPolicy,
    ReferenceMetadata,
    ResolvedGenerationPlan,
)
from app.providers.source_evidence import (
    ClaimStatus,
    SourceEvidenceStore,
    load_source_evidence,
    resolve_field_evidence,
)


def _supported(
    manifest: TypedModelCapabilityManifest,
    raw: dict[str, Any],
    store: SourceEvidenceStore,
    path: str,
    status: ClaimStatus,
) -> None:
    result = resolve_field_evidence(
        raw, pointer=path, scope=manifest.source_scope(), claim_status=status, store=store
    )
    if not result.officially_supported:
        raise ValueError(f"{path}: {result.blocker or 'CAPABILITY_UNVERIFIED'}")


def _fact(
    manifest: TypedModelCapabilityManifest,
    raw: dict[str, Any],
    store: SourceEvidenceStore,
    path: str,
    status: ClaimStatus,
    value: Any,
) -> None:
    """Check the used fact and every literal leaf, including specific overrides."""
    _supported(manifest, raw, store, path, status)
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _fact(manifest, raw, store, f"{path}/{index}", status, child)
    elif isinstance(value, dict):
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            _fact(manifest, raw, store, f"{path}/{escaped}", status, child)


def _limit(
    bound: CapabilityBound,
    value: float | None,
    *,
    lower: bool,
    path: str,
    manifest: TypedModelCapabilityManifest,
    raw: dict[str, Any],
    store: SourceEvidenceStore,
) -> None:
    if bound.kind == "unknown":
        raise ValueError(f"{path}: CAPABILITY_BOUND_UNKNOWN")
    _supported(manifest, raw, store, path, bound.claim_status)
    for key in ("kind", "value", "inclusive"):
        if key in raw_at(raw, path):
            _fact(manifest, raw, store, f"{path}/{key}", bound.claim_status, getattr(bound, key))
    if bound.kind == "unlimited":
        if lower:
            raise ValueError(f"{path}: minimum cannot be unlimited")
        return
    if value is None or not math.isfinite(value):
        raise ValueError(f"{path}: REFERENCE_METADATA_MISSING")
    assert bound.value is not None
    if ((value < bound.value) if lower else (value > bound.value)) or (
        not bound.inclusive and value == bound.value
    ):
        raise ValueError(f"{path}: CAPABILITY_LIMIT_EXCEEDED")


def _parameter(
    name: str,
    value: Any,
    spec: TypedParameter,
    path: str,
    manifest: TypedModelCapabilityManifest,
    raw: dict[str, Any],
    store: SourceEvidenceStore,
) -> None:
    _supported(manifest, raw, store, path, spec.claim_status)
    if spec.control not in {"native", "derived"}:
        raise ValueError(f"{path}: PARAMETER_NOT_WIRE_CONTROL")
    if not _parameter_type_matches(value, spec.type):
        raise ValueError(f"{path}: PARAMETER_TYPE_MISMATCH ({name})")
    for key in ("type", "control", "required"):
        if key in raw_at(raw, path):
            _fact(manifest, raw, store, f"{path}/{key}", spec.claim_status, getattr(spec, key))
    dimension_value = None
    if spec.dimension_bounds and isinstance(value, str):
        import re

        match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", value)
        if match:
            width, height = (int(term) for term in match.groups())
            dimension_value = {
                "min_pixels": width * height,
                "max_pixels": width * height,
                "min_aspect_ratio": width / height,
                "max_aspect_ratio": width / height,
                "min_width": width,
                "max_width": width,
                "min_height": height,
                "max_height": height,
            }
            for key, bound in spec.dimension_bounds.items():
                if key not in dimension_value:
                    raise ValueError("DIMENSION_BOUND_UNSUPPORTED")
                _limit(
                    bound,
                    dimension_value[key],
                    lower=key.startswith("min_"),
                    path=f"{path}/dimension_bounds/{key}",
                    manifest=manifest,
                    raw=raw,
                    store=store,
                )
    if spec.enum:
        _fact(manifest, raw, store, f"{path}/enum", spec.claim_status, spec.enum)
        if value not in spec.enum and dimension_value is None:
            raise ValueError(f"{path}: PARAMETER_ENUM_MISMATCH")
    if spec.type in {"integer", "number"}:
        for key, lower in (("minimum", True), ("maximum", False)):
            if spec.enum and getattr(spec, key).kind == "unknown":
                if key in raw_at(raw, path):
                    raise ValueError(f"{path}/{key}: CAPABILITY_BOUND_UNKNOWN")
                continue
            _limit(
                getattr(spec, key),
                value,
                lower=lower,
                path=f"{path}/{key}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    if spec.type == "array":
        for key, lower in (("min_items", True), ("max_items", False)):
            _limit(
                getattr(spec, key),
                len(value),
                lower=lower,
                path=f"{path}/{key}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    if spec.type == "string":
        for key, lower in (("min_length", True), ("max_length", False)):
            if key in raw_at(raw, path):
                _limit(
                    getattr(spec, key),
                    len(value),
                    lower=lower,
                    path=f"{path}/{key}",
                    manifest=manifest,
                    raw=raw,
                    store=store,
                )
    if spec.multiple_of is not None:
        _fact(manifest, raw, store, f"{path}/multiple_of", spec.claim_status, spec.multiple_of)
        if not isinstance(value, (float, int)) or not math.isclose(
            value / spec.multiple_of, round(value / spec.multiple_of)
        ):
            raise ValueError(f"{path}: PARAMETER_MULTIPLE_MISMATCH")


def _rules(
    rules: tuple[TypedConstraint, ...],
    path: str,
    effective: dict[str, Any],
    references: list[tuple[str, ReferenceMetadata]],
    manifest: TypedModelCapabilityManifest,
    raw: dict[str, Any],
    store: SourceEvidenceStore,
    *,
    predicates_only: bool = False,
) -> list[str]:
    transformations: list[str] = []
    counts = Counter(role for role, _ in references)
    for index, rule in enumerate(rules):
        pointer = f"{path}/{index}"
        _supported(manifest, raw, store, pointer, rule.claim_status)
        for key, value in raw_at(raw, pointer).items():
            if key not in {"claim_status", "description"}:
                _fact(manifest, raw, store, f"{pointer}/{key}", rule.claim_status, value)
        values = {**{role: count for role, count in counts.items() if count}, **effective}
        if not all(values.get(key) == value for key, value in rule.when.items()):
            continue
        if not all(values.get(key) is not None for key in rule.when_present):
            continue
        if (
            predicates_only
            and rule.kind == "requires_any"
            and not any(values.get(key) is not None for key in rule.require)
        ):
            raise ValueError(f"{pointer}: REQUIRED_ALTERNATIVE_MISSING")
        if (
            predicates_only
            and rule.kind != "requires_any"
            and any(values.get(key) is None for key in rule.require)
        ):
            raise ValueError(f"{pointer}: REQUIRED_VALUE_MISSING")
        if predicates_only and any(values.get(key) is not None for key in rule.forbid):
            raise ValueError(f"{pointer}: MUTUALLY_EXCLUSIVE_INPUT")
        if predicates_only and any(
            values.get(key) is not None and values[key] not in allowed
            for key, allowed in rule.allowed.items()
        ):
            raise ValueError(f"{pointer}: CONDITIONAL_VALUE_FORBIDDEN")
        if predicates_only and rule.kind == "sum_limit":
            numbers = [values.get(key, 0) for key in rule.sum_fields]
            assert isinstance(rule.value, (int, float))
            if (
                any(not isinstance(value, (int, float)) for value in numbers)
                or sum(numbers) > rule.value
            ):
                raise ValueError(f"{pointer}: COMBINED_COUNT_EXCEEDED")
        if rule.kind not in {"derived", "forced"}:
            continue
        value = rule.value
        if rule.kind == "derived":
            if rule.derivation == "reference_count":
                value = len(references)
            else:
                if any(item.duration_seconds is None for _, item in references):
                    raise ValueError(f"{pointer}: REFERENCE_DURATION_MISSING")
                value = sum(item.duration_seconds or 0 for _, item in references)
        assert rule.target is not None
        if predicates_only:
            if effective.get(rule.target) != value:
                raise ValueError(f"{pointer}: RULE_TRANSFORMATION_UNRESOLVED")
            continue
        if rule.target in effective and effective[rule.target] != value:
            raise ValueError(f"{pointer}: EXPLICIT_VALUE_CONFLICT")
        effective[rule.target] = value
        transformations.append(pointer)
    return transformations


def raw_at(raw: dict[str, Any], path: str) -> Any:
    node: Any = raw
    for key in path[1:].split("/"):
        node = (
            node[int(key)]
            if isinstance(node, list)
            else node[key.replace("~1", "/").replace("~0", "~")]
        )
    return node


def _contract(
    manifest: TypedModelCapabilityManifest,
    operation_name: str,
    contract_id: str,
    contract: TypedInputContract,
    references: list[tuple[str, ReferenceMetadata]],
    options: dict[str, Any],
    raw: dict[str, Any],
    store: SourceEvidenceStore,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    op = manifest.operations[cast(TypedOperationKind, operation_name)]
    root = f"/operations/{operation_name}"
    path = f"{root}/input_contracts/{contract_id}"
    _supported(manifest, raw, store, root, op.claim_status)
    _supported(manifest, raw, store, path, contract.claim_status)
    for key, lower in (("minimum_total_references", True), ("maximum_total_references", False)):
        _limit(
            getattr(contract, key),
            len(references),
            lower=lower,
            path=f"{path}/{key}",
            manifest=manifest,
            raw=raw,
            store=store,
        )
    counts = Counter(role for role, _ in references)
    if not counts.keys() <= contract.input_slots.keys():
        raise ValueError("INPUT_ROLE_UNDECLARED")
    for role, slot in contract.input_slots.items():
        slot_path = f"{path}/input_slots/{role}"
        _supported(manifest, raw, store, slot_path, slot.claim_status)
        count = counts.get(role, 0)
        if "required" in raw_at(raw, slot_path):
            _fact(manifest, raw, store, f"{slot_path}/required", slot.claim_status, slot.required)
        for key, lower in (("minimum", True), ("maximum", False)):
            _limit(
                getattr(slot, key),
                count,
                lower=lower,
                path=f"{slot_path}/{key}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
        if slot.required and count == 0:
            raise ValueError(f"{slot_path}: REQUIRED_REFERENCE_MISSING")
    for role, item in references:
        slot = contract.input_slots[role]
        pointer = f"{path}/input_slots/{role}"
        for key in ("media_types", "ordering", "codecs", "aspect_ratios"):
            if key in raw_at(raw, pointer):
                _fact(
                    manifest, raw, store, f"{pointer}/{key}", slot.claim_status, getattr(slot, key)
                )
        if not slot.media_types or not any(
            fnmatch(item.mime_type.lower(), mime.lower()) for mime in slot.media_types
        ):
            raise ValueError(f"{pointer}: MEDIA_TYPE_UNSUPPORTED_OR_UNKNOWN")
        if slot.ordering != "preserve":
            raise ValueError(f"{pointer}: REFERENCE_ORDER_UNKNOWN")
        if slot.codecs and item.codec not in slot.codecs:
            raise ValueError(f"{pointer}: CODEC_UNSUPPORTED_OR_MISSING")
        if slot.aspect_ratios and (
            item.width is None
            or item.height is None
            or not any(
                abs(item.width / item.height - int(r.split(":")[0]) / int(r.split(":")[1])) < 0.01
                for r in slot.aspect_ratios
            )
        ):
            raise ValueError(f"{pointer}: ASPECT_RATIO_UNSUPPORTED_OR_MISSING")
        keys: list[tuple[str, float | None, bool]] = [("max_bytes", item.byte_size, False)]
        if item.mime_type.lower().startswith(("image/", "video/")):
            keys += [
                ("min_width", item.width, True),
                ("max_width", item.width, False),
                ("min_height", item.height, True),
                ("max_height", item.height, False),
            ]
            pixels = item.width * item.height if item.width and item.height else None
            ratio = item.width / item.height if item.width and item.height else None
            for key, value, lower in (
                ("min_pixels", pixels, True),
                ("max_pixels", pixels, False),
                ("min_aspect_ratio", ratio, True),
                ("max_aspect_ratio", ratio, False),
            ):
                if key in raw_at(raw, pointer):
                    keys.append((key, value, lower))
        if item.mime_type.lower().startswith(("video/", "audio/")):
            keys += [
                ("min_duration_seconds", item.duration_seconds, True),
                ("max_duration_seconds", item.duration_seconds, False),
            ]
        if item.mime_type.lower().startswith("video/"):
            keys += [("min_fps", item.fps, True), ("max_fps", item.fps, False)]
        for key, value, lower in keys:
            _limit(
                getattr(slot, key),
                value,
                lower=lower,
                path=f"{pointer}/{key}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    if references:
        total_bytes = (
            sum(item.byte_size or 0 for _, item in references)
            if all(item.byte_size is not None for _, item in references)
            else None
        )
        _limit(
            contract.maximum_total_bytes,
            total_bytes,
            lower=False,
            path=f"{path}/maximum_total_bytes",
            manifest=manifest,
            raw=raw,
            store=store,
        )
    for role, bound in contract.max_total_duration_seconds.items():
        items = [item for selected_role, item in references if selected_role == role]
        if items:
            total = (
                sum(item.duration_seconds or 0 for item in items)
                if all(item.duration_seconds is not None for item in items)
                else None
            )
            _limit(
                bound,
                total,
                lower=False,
                path=f"{path}/max_total_duration_seconds/{role}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    for role, bound in contract.min_total_duration_seconds.items():
        items = [item for selected_role, item in references if selected_role == role]
        if items:
            total = (
                sum(item.duration_seconds or 0 for item in items)
                if all(item.duration_seconds is not None for item in items)
                else None
            )
            _limit(
                bound,
                total,
                lower=True,
                path=f"{path}/min_total_duration_seconds/{role}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    for role, bound in contract.max_total_bytes_by_role.items():
        items = [item for selected_role, item in references if selected_role == role]
        if items:
            total_bytes = (
                sum(item.byte_size or 0 for item in items)
                if all(item.byte_size is not None for item in items)
                else None
            )
            _limit(
                bound,
                total_bytes,
                lower=False,
                path=f"{path}/max_total_bytes_by_role/{role}",
                manifest=manifest,
                raw=raw,
                store=store,
            )
    declared = {**op.output_options, **contract.output_options}
    effective: dict[str, Any] = {}
    paths = {key: f"{root}/output_options/{key}" for key in op.output_options}
    paths.update({key: f"{path}/output_options/{key}" for key in contract.output_options})
    for name, spec in declared.items():
        if (
            spec.claim_status != "documented_supported"
            and name not in options
            and not spec.required
        ):
            continue
        if spec.required is None:
            raise ValueError(f"{paths[name]}/required: OUTPUT_REQUIREDNESS_UNKNOWN")
        _fact(manifest, raw, store, f"{paths[name]}/required", spec.claim_status, spec.required)
        if spec.default_status == "documented_supported":
            _fact(
                manifest,
                raw,
                store,
                f"{paths[name]}/default_status",
                spec.claim_status,
                spec.default_status,
            )
            _fact(manifest, raw, store, f"{paths[name]}/default", spec.claim_status, spec.default)
            _parameter(name, spec.default, spec, paths[name], manifest, raw, store)
            effective[name] = spec.default
    for name, value in options.items():
        if name not in declared:
            raise ValueError(f"{name}: OUTPUT_OPTION_UNDECLARED")
        _parameter(name, value, declared[name], paths[name], manifest, raw, store)
        effective[name] = value
    transforms = [
        *_rules(op.constraints, f"{root}/constraints", effective, references, manifest, raw, store),
        *_rules(
            contract.constraints, f"{path}/constraints", effective, references, manifest, raw, store
        ),
    ]
    # Transformations only add values; conflicting assignments always block.
    # Repeat to resolve predicates activated by a later declared derivation.
    for _ in range(len(op.constraints) + len(contract.constraints) + 1):
        previous = effective.copy()
        transforms.extend(
            _rules(
                op.constraints, f"{root}/constraints", effective, references, manifest, raw, store
            )
        )
        transforms.extend(
            _rules(
                contract.constraints,
                f"{path}/constraints",
                effective,
                references,
                manifest,
                raw,
                store,
            )
        )
        if previous == effective:
            break
    else:
        raise ValueError("RULE_TRANSFORMATION_UNSTABLE")
    transforms = list(dict.fromkeys(transforms))
    _rules(
        op.constraints,
        f"{root}/constraints",
        effective,
        references,
        manifest,
        raw,
        store,
        predicates_only=True,
    )
    _rules(
        contract.constraints,
        f"{path}/constraints",
        effective,
        references,
        manifest,
        raw,
        store,
        predicates_only=True,
    )
    for name, value in effective.items():
        if name not in declared:
            raise ValueError(f"{name}: RULE_TARGET_UNDECLARED")
        _parameter(name, value, declared[name], paths[name], manifest, raw, store)
    if any(spec.required and name not in effective for name, spec in declared.items()):
        raise ValueError("OUTPUT_OPTION_REQUIRED")
    return effective, tuple(transforms)


def resolve_typed_contract(
    *,
    manifest: TypedModelCapabilityManifest,
    operation_name: str,
    selected: list[tuple[UUID, str]],
    references: list[tuple[str, ReferenceMetadata]],
    options: dict[str, Any],
    policy: ProductCapabilityPolicy,
    evidence_store: SourceEvidenceStore | None,
    prompt: str,
) -> ResolvedGenerationPlan:
    store = evidence_store if evidence_store is not None else load_source_evidence()
    raw = manifest.model_dump(mode="json", exclude_unset=True)
    operation = manifest.operations.get(cast(TypedOperationKind, operation_name))
    if operation is None:
        raise CapabilityResolutionError("OPERATION_UNSUPPORTED", operation_name)
    if not operation.input_contracts:
        raise CapabilityResolutionError("INPUT_CONTRACT_NOT_DECLARED", operation_name)
    if operation.prompt_spec is not None:
        try:
            _parameter(
                "prompt",
                prompt,
                operation.prompt_spec,
                f"/operations/{operation_name}/prompt_spec",
                manifest,
                raw,
                store,
            )
        except (ValueError, KeyError) as exc:
            raise CapabilityResolutionError("PROMPT_CONTRACT_UNSUPPORTED", str(exc)) from exc
    matches = []
    reasons = {}
    for name, contract in operation.input_contracts.items():
        try:
            effective, transformations = _contract(
                manifest, operation_name, name, contract, references, options, raw, store
            )
        except (ValueError, KeyError, IndexError) as exc:
            reasons[name] = str(exc)
        else:
            matches.append((name, effective, transformations))
    if not matches:
        raise CapabilityResolutionError(
            "MODEL_INPUT_COMBINATION_UNSUPPORTED",
            "no reviewed input contract accepts this request",
            reasons=reasons,
        )
    if len(matches) != 1:
        raise CapabilityResolutionError("MANIFEST_CONTRACT_AMBIGUOUS", "ambiguous input contracts")
    name, effective, transformations = matches[0]
    if name not in policy.allowed_contracts:
        raise CapabilityResolutionError("PRODUCT_CAPABILITY_CLOSED", name)
    if policy.allowed_options is not None and not effective.keys() <= policy.allowed_options:
        raise CapabilityResolutionError("PRODUCT_OPTION_CLOSED", "effective option is closed")
    return ResolvedGenerationPlan(
        provider_type=manifest.provider_type,
        protocol_profile=manifest.protocol_profile,
        model_id=manifest.model_id,
        model_revision=manifest.model_revision,
        operation=operation_name,
        matched_contract=name,
        reference_ids=tuple(item for item, _ in selected),
        reference_roles=tuple(role for _, role in selected),
        effective_options=effective,
        transformations=transformations,
    )
