"""Offline provenance for the single Manifest; source metadata never defines abilities."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ClaimStatus = Literal["documented_supported", "documented_unsupported", "unknown", "conflicting"]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SourceScope(EvidenceModel):
    provider_type: str = Field(min_length=1)
    protocol_profile: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    api_version: str = Field(default="unknown", min_length=1)
    region: str = Field(default="unknown", min_length=1)

    def is_exact(self) -> bool:
        return all(
            value.strip() and value == value.strip() and value.casefold() != "unknown"
            for value in (
                self.provider_type,
                self.protocol_profile,
                self.model_id,
                self.api_version,
                self.region,
            )
        )


class SourceRecord(EvidenceModel):
    source_id: str = Field(min_length=1)
    kind: Literal[
        "official_api_doc", "official_sdk", "official_example", "official_notice", "synthetic_test"
    ]
    url: str = Field(pattern=r"^https://[^\s]+$")
    applies_to: tuple[SourceScope, ...]


class SourceSnapshot(EvidenceModel):
    source_snapshot_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    capture_status: Literal["captured", "unavailable"]
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    locator: str
    review_status: Literal["unreviewed", "reviewed"] = "unreviewed"
    reviewed_scopes: tuple[SourceScope, ...] = ()
    evidence_summary: str = ""

    @model_validator(mode="after")
    def validate_capture(self) -> SourceSnapshot:
        if (self.capture_status == "captured") != (self.content_sha256 is not None):
            raise ValueError(
                "captured sources require a real hash; unavailable sources have no hash"
            )
        if self.review_status == "reviewed" and (
            self.capture_status != "captured"
            or not self.reviewed_scopes
            or any(not scope.is_exact() for scope in self.reviewed_scopes)
        ):
            raise ValueError(
                "source review requires captured content and exact reviewed applicability"
            )
        return self


class SourceCheck(EvidenceModel):
    check_id: str = Field(min_length=1)
    source_snapshot_ref: str
    checked_at: datetime
    result: Literal["captured_unreviewed", "unchanged", "changed", "temporary_error", "unavailable"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    observed_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    note: str = ""

    @model_validator(mode="after")
    def require_timezone(self) -> SourceCheck:
        if self.checked_at.utcoffset() is None:
            raise ValueError("source checks require a timezone-aware timestamp")
        return self


class EvidenceReview(EvidenceModel):
    covers: str
    reviewed_subtree_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: str = Field(min_length=1)
    review_kind: Literal["human", "authorized_agent", "synthetic_test"]
    locator: str = Field(min_length=1)


class SourceEvidenceStore(EvidenceModel):
    schema_version: Literal["1"] = "1"
    sources: tuple[SourceRecord, ...] = ()
    snapshots: tuple[SourceSnapshot, ...] = ()
    checks: tuple[SourceCheck, ...] = ()

    @model_validator(mode="after")
    def validate_relations(self) -> SourceEvidenceStore:
        records = {source.source_id: source for source in self.sources}
        snapshots = {snapshot.source_snapshot_id: snapshot for snapshot in self.snapshots}
        if len(records) != len(self.sources) or len({s.url for s in self.sources}) != len(
            self.sources
        ):
            raise ValueError(
                "source IDs and URLs must be unique; use explicit shared applicability"
            )
        if len(snapshots) != len(self.snapshots):
            raise ValueError("snapshot IDs must be unique")
        if len({check.check_id for check in self.checks}) != len(self.checks):
            raise ValueError("check IDs must be unique")
        for snapshot in self.snapshots:
            source = records.get(snapshot.source_id)
            if source is None or any(
                scope not in source.applies_to for scope in snapshot.reviewed_scopes
            ):
                raise ValueError(
                    "snapshot references an unknown source or undeclared applicability"
                )
        if any(check.source_snapshot_ref not in snapshots for check in self.checks):
            raise ValueError("check references an unknown snapshot")
        for check in self.checks:
            snapshot = snapshots[check.source_snapshot_ref]
            if check.result in {"unchanged", "captured_unreviewed"} and (
                snapshot.capture_status != "captured"
                or check.observed_content_sha256 != snapshot.content_sha256
            ):
                raise ValueError("unchanged/captured check must match the captured snapshot hash")
            if check.result == "changed" and (
                check.observed_content_sha256 is None
                or check.observed_content_sha256 == snapshot.content_sha256
            ):
                raise ValueError("changed check requires a different observed content hash")
        return self

    def append_source(self, source: SourceRecord) -> SourceEvidenceStore:
        records = list(self.sources)
        for index, previous in enumerate(records):
            if previous.source_id != source.source_id:
                continue
            if (previous.url, previous.kind) != (source.url, source.kind):
                raise ValueError("stable source identity cannot change its URL or origin kind")
            if not set(previous.applies_to) <= set(source.applies_to):
                raise ValueError("source applicability history cannot be removed")
            if previous == source:
                return self
            records[index] = source
            break
        else:
            records.append(source)
        return SourceEvidenceStore.model_validate({**self.model_dump(), "sources": records})

    def append_snapshot(self, snapshot: SourceSnapshot) -> SourceEvidenceStore:
        for previous in self.snapshots:
            if previous.source_snapshot_id == snapshot.source_snapshot_id:
                if previous != snapshot:
                    raise ValueError("immutable source snapshot cannot be rewritten")
                return self
        return SourceEvidenceStore.model_validate(
            {**self.model_dump(), "snapshots": (*self.snapshots, snapshot)}
        )

    def append_check(self, check: SourceCheck) -> SourceEvidenceStore:
        for previous in self.checks:
            if previous.check_id == check.check_id:
                if previous != check:
                    raise ValueError("append-only source check cannot be rewritten")
                return self
        return SourceEvidenceStore.model_validate(
            {**self.model_dump(), "checks": (*self.checks, check)}
        )


_AUDIT_KEYS = frozenset(
    {
        "evidence_group_ref",
        "source_snapshot_ref",
        "evidence_review",
        "source_url",
        "locator",
        "checked_at",
        "reviewed_at",
        "review_notes",
    }
)
_NAMED_FIELDS = frozenset(
    {
        "operations",
        "input_contracts",
        "input_slots",
        "output_options",
        "parameters",
        "properties",
        "evidence_overrides",
        "common_options",
        "native_options",
        "options",
        "modes",
        "capability_specs",
        "reference_constraints",
    }
)
_LITERAL_FIELDS = frozenset(
    {
        "value",
        "default",
        "enum",
        "when",
        "allowed",
        "requires",
        "exclusion",
        "conditional",
        "derived",
        "forced",
    }
)


def _semantic_content(value: Any, *, named: bool = False) -> Any:
    if isinstance(value, list):
        return [_semantic_content(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: deepcopy(child)
        if not named and key in _LITERAL_FIELDS
        else _semantic_content(child, named=not named and key in _NAMED_FIELDS)
        for key, child in value.items()
        if named or key not in _AUDIT_KEYS
    }
    if not named:
        result.pop("evidence_overrides", None)
    return result


def _overrides(manifest: dict[str, Any]) -> dict[tuple[str, ...], tuple[int, dict[str, Any]]]:
    """One absolute-path priority rule shared by Hash and field resolution."""
    result: dict[tuple[str, ...], tuple[int, dict[str, Any]]] = {}

    def visit(node: Any, path: tuple[str, ...], *, named: bool = False) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, (*path, str(index)))
            return
        if not isinstance(node, dict):
            return
        if not named:
            for relative, override in node.get("evidence_overrides", {}).items():
                if not isinstance(override, dict):
                    raise ValueError("evidence override must be an object")
                target = (*path, *_segments("/" + relative.removeprefix("/")))
                _at(manifest, list(target))  # Overrides must refer to real declared fields.
                if target not in result or len(path) > result[target][0]:
                    result[target] = (len(path), override)
        for key, child in node.items():
            if not named and (
                key in _AUDIT_KEYS or key in _LITERAL_FIELDS or key == "evidence_overrides"
            ):
                continue
            visit(child, (*path, key), named=not named and key in _NAMED_FIELDS)

    visit(manifest, ())
    return result


def _effective_tree(manifest: dict[str, Any]) -> Any:
    tree = _semantic_content(manifest)
    for target, (_owner, override) in sorted(
        _overrides(manifest).items(), key=lambda item: len(item[0])
    ):
        if "claim_status" not in override:
            continue
        parent = _at(tree, list(target[:-1]))
        value = _at(parent, list(target[-1:]))
        projected = (
            {**value, "claim_status": override["claim_status"]}
            if isinstance(value, dict)
            else {"value": value, "claim_status": override["claim_status"]}
        )
        if isinstance(parent, list):
            parent[int(target[-1])] = projected
        else:
            parent[target[-1]] = projected
    return tree


def reviewed_manifest_subtree_hash(manifest: dict[str, Any], covers: str) -> str:
    """Hash the effective capability subtree, including exception support states."""
    subtree = _at(_effective_tree(manifest), _segments(covers))
    content = json.dumps(subtree, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def _segments(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError("evidence paths require an explicit JSON pointer")
    import re

    parts = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", part) for part in parts):
        raise ValueError("invalid JSON pointer escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in parts]


def _at(tree: Any, segments: list[str]) -> Any:
    for segment in segments:
        if isinstance(tree, list):
            if not segment.isdecimal() or (len(segment) > 1 and segment.startswith("0")):
                raise ValueError("invalid JSON pointer array index")
            tree = tree[int(segment)]
        else:
            tree = tree[segment]
    return tree


@dataclass(frozen=True)
class EvidenceResolution:
    source_snapshot_ref: str | None
    resolution: Literal["explicit", "inherited", "missing"]
    claim_status: ClaimStatus
    blocker: str | None

    @property
    def officially_supported(self) -> bool:
        return self.blocker is None and self.claim_status == "documented_supported"


def resolve_field_evidence(
    manifest: dict[str, Any],
    *,
    pointer: str,
    scope: SourceScope,
    claim_status: ClaimStatus,
    store: SourceEvidenceStore,
) -> EvidenceResolution:
    """Resolve association only; parent groups never manufacture a field's status."""
    parts = _segments(pointer)
    _at(manifest, parts)
    binding = None
    binding_depth = 0
    explicit_override = False
    for depth in range(len(parts), -1, -1):
        node = _at(manifest, parts[:depth])
        if not isinstance(node, dict):
            continue
        if binding is None and ("evidence_group_ref" in node or "source_snapshot_ref" in node):
            binding, binding_depth = node, depth
    override_matches = [
        (len(target), owner, override)
        for target, (owner, override) in _overrides(manifest).items()
        if tuple(parts[: len(target)]) == target
    ]
    if override_matches:
        _specificity, binding_depth, binding = max(override_matches, key=lambda match: match[:2])
        explicit_override = True
    if not isinstance(binding, dict):
        return EvidenceResolution(None, "missing", claim_status, "EVIDENCE_MISSING")
    reference = binding.get("source_snapshot_ref") or binding.get("evidence_group_ref")
    declared_status: ClaimStatus = "unknown"
    field_status_found = False
    effective = _effective_tree(manifest)
    for depth in range(len(parts), binding_depth, -1):
        node = _at(effective, parts[:depth])
        if isinstance(node, dict) and "claim_status" in node:
            declared_status = node["claim_status"]
            field_status_found = True
            break
    if not field_status_found and (
        binding_depth == len(parts)
        or any(key in binding for key in ("value", "type", "media_types"))
    ):
        declared_status = _at(effective, parts[:binding_depth]).get("claim_status", "unknown")
    status = declared_status
    if status not in {"documented_supported", "documented_unsupported", "unknown", "conflicting"}:
        return EvidenceResolution(reference, "explicit", "unknown", "CLAIM_STATUS_INVALID")
    resolution: Literal["explicit", "inherited", "missing"] = (
        "explicit" if explicit_override or binding_depth == len(parts) else "inherited"
    )
    if not explicit_override and status != claim_status:
        return EvidenceResolution(reference, resolution, status, "CLAIM_STATUS_MISMATCH")
    result = EvidenceResolution(reference, resolution, status, None)
    snapshot = next(
        (item for item in store.snapshots if item.source_snapshot_id == reference), None
    )
    if snapshot is None:
        return EvidenceResolution(reference, resolution, status, "SOURCE_SNAPSHOT_MISSING")
    if snapshot.capture_status != "captured" or snapshot.review_status != "reviewed":
        return EvidenceResolution(reference, resolution, status, "SOURCE_UNREVIEWED_OR_UNAVAILABLE")
    if not scope.is_exact() or scope not in snapshot.reviewed_scopes:
        return EvidenceResolution(reference, resolution, status, "SOURCE_SCOPE_MISMATCH")
    try:
        review = EvidenceReview.model_validate(binding.get("evidence_review"))
        covered = _segments(review.covers)
        if parts[: len(covered)] != covered:
            raise ValueError("review does not cover requested capability field")
        actual = reviewed_manifest_subtree_hash(manifest, review.covers)
    except (ValueError, KeyError, IndexError, TypeError):
        return EvidenceResolution(reference, resolution, status, "EVIDENCE_REVIEW_INVALID")
    if actual != review.reviewed_subtree_hash:
        return EvidenceResolution(reference, resolution, status, "EVIDENCE_REVIEW_STALE")
    source = next(item for item in store.sources if item.source_id == snapshot.source_id)
    if source.kind == "synthetic_test" or review.review_kind == "synthetic_test":
        return EvidenceResolution(reference, resolution, status, "SYNTHETIC_EVIDENCE_NOT_OFFICIAL")
    if status != "documented_supported":
        return EvidenceResolution(reference, resolution, status, f"CLAIM_{status.upper()}")
    return result


def load_source_evidence(root: Path | None = None) -> SourceEvidenceStore:
    """Load local metadata only; no HTTP, credentials, or capabilities are read."""
    directory = root or Path(__file__).with_name("model_sources")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate source metadata key: {key}")
            result[key] = value
        return result

    data: dict[str, Any] = {"schema_version": "1"}
    for name, key in (
        ("source_registry.json", "sources"),
        ("source_snapshots.json", "snapshots"),
        ("source_checks.json", "checks"),
    ):
        raw = json.loads(
            (directory / name).read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        if set(raw) != {"schema_version", key} or raw["schema_version"] != "1":
            raise ValueError(f"unsupported source metadata file contract: {name}")
        data[key] = raw[key]
    return SourceEvidenceStore.model_validate(data)
