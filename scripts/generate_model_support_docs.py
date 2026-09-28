"""Generate the model support matrix from catalog revisions and optional Binding facts.

With no Binding snapshot, account and execution status remain workspace-specific.
The optional JSON file is an array of redacted Binding status records and may be
used to write a workspace-specific report outside the committed docs tree.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.manifest import ModelCapabilityManifest, OperationManifest, ParameterSpec

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "generated" / "MODEL_SUPPORT.md"
Identity = tuple[str, str, str, str]


def _binding_statuses(path: Path | None) -> dict[Identity, list[dict[str, Any]]]:
    if path is None:
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Binding snapshot must be a JSON array")
    grouped: dict[Identity, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Binding snapshot item must be an object")
        identity = tuple(
            str(record[key])
            for key in ("provider_type", "protocol_profile", "model_id", "model_revision")
        )
        if len(identity) != 4:
            raise ValueError("invalid Binding identity")
        for key in ("enabled", "account_verified", "quality_gated"):
            if not isinstance(record.get(key), bool):
                raise ValueError(f"Binding {key} must be boolean")
        grouped[identity].append(record)
    return grouped


def _value(spec: ParameterSpec) -> str:
    if spec.enum:
        return ", ".join(str(value) for value in spec.enum)
    if spec.minimum is not None and spec.maximum is not None:
        return f"{spec.minimum:g}–{spec.maximum:g}"
    if spec.default is not None:
        return str(spec.default)
    return "—"


def _option(operation: OperationManifest, name: str) -> str:
    spec = operation.output_options.get(name)
    if spec is not None:
        return _value(spec)
    raw = operation.output_constraints.get(name)
    if isinstance(raw, dict):
        allowed = raw.get("allowed")
        if isinstance(allowed, list):
            return ", ".join(str(value) for value in allowed)
    return str(raw) if raw is not None else "—"


def _references(operation: OperationManifest) -> str:
    limits: dict[str, int] = {}
    unknown: set[str] = set()
    for contract in operation.input_contracts.values():
        for role, slot in contract.input_slots.items():
            if slot.maximum is not None and slot.maximum > 0:
                limits[role] = max(limits.get(role, 0), slot.maximum)
            elif slot.maximum is None:
                unknown.add(role)
    if not operation.input_contracts:
        limits = {
            role: constraint.max
            for role, constraint in operation.reference_constraints.items()
            if constraint.max > 0
        }
        capability_roles = {
            "video.i2v.first_frame": "first_frame",
            "video.i2v.last_frame": "last_frame",
            "video.reference.image": "reference_image",
            "video.reference.video": "reference_video",
            "video.reference.audio": "reference_audio",
            "image.i2i": "reference_image",
        }
        unknown.update(
            capability_roles[capability]
            for capability in operation.capabilities
            if capability in capability_roles and capability_roles[capability] not in limits
        )
    parts = [f"{role} ≤ {count}" for role, count in sorted(limits.items())]
    parts.extend(f"{role} (limit unverified)" for role in sorted(unknown - limits.keys()))
    summary = ", ".join(parts)
    return summary or "none documented"


def _support_state(
    manifest: ModelCapabilityManifest,
    lifecycle: str,
    bindings: list[dict[str, Any]] | None,
) -> tuple[str, str, str]:
    if bindings is None:
        return (
            "workspace-specific",
            "no"
            if lifecycle not in {"active", "legacy", "deprecated"}
            or manifest.implementation_status != "contract_tested"
            else "requires verified Binding",
            "workspace-specific",
        )
    verified = any(item["enabled"] and item["account_verified"] for item in bindings)
    executable = (
        lifecycle in {"active", "legacy", "deprecated"}
        and manifest.implementation_status == "contract_tested"
        and verified
    )
    certified = executable and any(
        item["enabled"] and item["account_verified"] and item["quality_gated"]
        for item in bindings
    )
    return (
        "verified" if verified else "unverified",
        "yes" if executable else "no",
        "yes" if certified else "no",
    )


def render_model_support(*, binding_snapshot: Path | None = None) -> str:
    statuses = _binding_statuses(binding_snapshot)
    rows = [
        "# Model support matrix",
        "",
        "Generated from `backend/app/providers/model_catalog/` and optional redacted "
        "Binding status.",
        "Provider capabilities are recorded independently of the Workbench product subset.",
        "A documented preview cannot execute. A verified Binding is workspace-specific.",
        "",
        "| Provider | Model / revision | Lifecycle | Media | References | Duration | "
        "Resolution / size | Account | Executable | Certified |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in sorted(ModelCatalogLoader().load(), key=lambda value: value.identity):
        manifest = ModelCapabilityManifest.model_validate(item.as_dict())
        operation = next(iter(manifest.operations.values()), None)
        refs = _references(operation) if operation is not None else "not documented"
        duration = _option(operation, "duration_seconds") if operation is not None else "—"
        resolution = (
            _option(operation, "resolution")
            if manifest.media_kind == "video" and operation is not None
            else _option(operation, "size") if operation is not None else "—"
        )
        if resolution == "—" and operation is not None:
            resolution = _option(operation, "aspect_ratio")
        account, executable, certified = _support_state(
            manifest,
            item.publication_lifecycle,
            statuses.get(item.identity) if binding_snapshot is not None else None,
        )
        cells = (
            manifest.provider_type,
            f"`{manifest.model_id}` / `{manifest.model_revision}`",
            item.publication_lifecycle,
            manifest.media_kind,
            refs,
            duration,
            resolution,
            account,
            executable,
            certified,
        )
        rows.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
    rows.extend(
        ("", "No account verification or certification is inferred from a catalog manifest.", "")
    )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding-status-json", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render_model_support(binding_snapshot=args.binding_status_json)
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != content:
            raise SystemExit(f"generated model support document is stale: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
