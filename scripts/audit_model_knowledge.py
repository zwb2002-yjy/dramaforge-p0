"""Report typed Catalog facts against a frozen baseline, with separate metrics.

This command performs no network, database access, or publication. Optional
baseline mappings are review evidence, never a writable capability authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.knowledge_projection import project_model_knowledge
from app.providers.source_evidence import read_capability_pointer

ROOT = Path(__file__).resolve().parents[1]


CLASSIFICATIONS = frozenset(
    {
        "structured",
        "explicit_unknown",
        "conflicting",
        "documented_unsupported",
        "source_annotation",
        "publication_fact",
    }
)
MAPPING_KEYS = frozenset(
    {
        "claim_id",
        "classification",
        "schema_path",
        "mapping_review",
        "transformation",
        "candidate_identity",
        "candidate_manifest_hash",
        "expected_value",
    }
)


def _classify_baseline_claims(
    claims: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    candidates: dict[tuple[str, ...], Any],
) -> list[dict[str, Any]]:
    claim_ids = {claim["id"] for claim in claims}
    if len(claim_ids) != len(claims):
        raise ValueError("duplicate baseline claim ID")
    by_claim: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.keys() - MAPPING_KEYS:
            raise ValueError("invalid baseline mapping fields")
        claim_id = mapping.get("claim_id")
        if claim_id not in claim_ids or claim_id in by_claim:
            raise ValueError("unknown or duplicate baseline claim mapping")
        if mapping.get("classification") not in CLASSIFICATIONS:
            raise ValueError("invalid baseline claim classification")
        if (
            not isinstance(mapping.get("mapping_review"), str)
            or not mapping["mapping_review"].strip()
        ):
            raise ValueError("baseline mapping requires an explicit review")
        by_claim[claim_id] = mapping
    classified: list[dict[str, Any]] = []
    for claim in claims:
        mapping = by_claim.get(claim["id"])
        if mapping is None:
            classified.append(
                {"claim_id": claim["id"], "classification": "not_assessed", "schema_path": None}
            )
            continue
        row = {
            "claim_id": claim["id"],
            "original_identity": claim["identity"],
            "original_value": claim["value"],
            **mapping,
        }
        pointer = mapping.get("schema_path")
        annotation = mapping["classification"] in {"source_annotation", "publication_fact"}
        if annotation:
            if pointer is not None:
                raise ValueError("source/publication observations are not capability mappings")
        else:
            if not isinstance(pointer, str) or not pointer.startswith("/operations/"):
                raise ValueError("capability mapping needs a declared operations pointer")
            candidate = candidates[tuple(claim["identity"][:3])]
            if (
                tuple(mapping.get("candidate_identity", ())) != candidate.identity
                or mapping.get("candidate_manifest_hash") != candidate.manifest_hash
            ):
                raise ValueError("baseline mapping review has a stale candidate identity/hash")
            value = read_capability_pointer(candidate.as_dict(), pointer)
            if "expected_value" not in mapping or json.dumps(
                value, sort_keys=True, allow_nan=False
            ) != json.dumps(mapping["expected_value"], sort_keys=True, allow_nan=False):
                raise ValueError("candidate value differs from the explicitly reviewed mapping")
            if value != claim["value"] and (
                not isinstance(mapping.get("transformation"), str)
                or not mapping["transformation"].strip()
            ):
                raise ValueError("changed representation needs an explicit mapping transformation")
            row["candidate_identity"] = candidate.identity
            row["mapped_value"] = value
        classified.append(row)
    return classified


def build_knowledge_audit(
    *,
    baseline: dict[str, Any] | None = None,
    mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    loaded = ModelCatalogLoader().load()
    typed = [item for item in loaded if item.as_dict().get("schema_version") == "2"]
    candidates = {item.identity[:3]: item for item in typed}
    if len(candidates) != len(typed):
        raise ValueError("audit needs an explicit candidate revision per model")
    models = []
    fields = []
    for item in typed:
        report = project_model_knowledge(item.as_dict())
        models.append(
            {
                "identity": item.identity,
                "manifest_hash": item.manifest_hash,
                "lifecycle": item.publication_lifecycle,
                "operations": list(report.operations),
                "claim_counts": report.claim_counts,
                "unknown_bounds": report.unknown_bounds,
                "blockers": report.blockers,
                "implementation": "not_implemented",
                "product_open": False,
                "account": "not_checked",
            }
        )
        fields.extend({"identity": item.identity, **field.model_dump()} for field in report.fields)
    frozen = [item for item in (baseline or {}).get("inventory", []) if item["in_initial_scope"]]
    old_by_identity = {item.identity: item for item in loaded}
    frozen_checks = []
    for old in frozen:
        current = old_by_identity.get(tuple(old["identity"]))
        frozen_checks.append(
            {
                "identity": old["identity"],
                "represented": tuple(old["identity"][:3]) in candidates,
                "hash_unchanged": current is not None
                and current.manifest_hash == old["manifest_hash"],
                "bytes_unchanged": current is not None
                and hashlib.sha256(current.source_path.read_bytes()).hexdigest()
                == old["file_sha256"],
            }
        )
    claims = (baseline or {}).get("official_claims", [])
    classified = _classify_baseline_claims(claims, mappings or [], candidates)
    counts = Counter(field["claim_status"] for field in fields)
    return {
        "schema_version": "1",
        "checked_at": datetime.now(UTC).isoformat(),
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_worktree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True
            ).strip()
        ),
        "baseline_inventory_sha256": (baseline or {}).get("inventory_sha256"),
        "metrics": {
            "inventory": {
                "candidate_models": len(typed),
                "frozen_revisions": len(frozen),
                "represented_frozen_revisions": sum(row["represented"] for row in frozen_checks),
            },
            "claim_classification": {
                "typed_fact_groups": len(fields),
                "states": dict(counts),
                "baseline_claims": len(claims),
                "baseline_classified": sum(
                    row["classification"] != "not_assessed" for row in classified
                ),
            },
            "structured_mapping": {
                "mapped_baseline_claims": sum(bool(row.get("schema_path")) for row in classified),
                "source_annotations": sum(
                    row["classification"] == "source_annotation" for row in classified
                ),
                "publication_facts": sum(
                    row["classification"] == "publication_fact" for row in classified
                ),
            },
            "official_evidence": {
                "reviewed_supported_fact_groups": sum(
                    field["blocker"] is None and field["claim_status"] == "documented_supported"
                    for field in fields
                ),
                "candidate_positive_fact_groups": counts.get("documented_supported", 0),
            },
            "compiler_contracts": {
                "new_typed_implemented": 0,
                "old_exact_fixtures": sum(bool(item.get("exact_fixture_paths")) for item in frozen),
                "tests": "not run by this audit",
            },
            "product_open": {"new_typed_contracts": 0, "account_verified_by_audit": 0},
        },
        "models": models,
        "fields": fields,
        "baseline_claims": classified,
        "frozen_checks": frozen_checks,
        "real_provider_requests": 0,
        "new_active_publications": 0,
        "limitations": [
            "Source facts do not verify account access or media quality.",
            "Typed candidates are not executable; legacy Create qualification is a separate gate.",
            "Fact groups, source applicability, Compiler fixtures and openness use separate totals.",
            "Mapping reviews bind values and transformations, not automatic semantic proof.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--mappings", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "tmp") or output.exists():
        raise ValueError("write only to a new report directory inside tmp")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    mappings = json.loads(args.mappings.read_text(encoding="utf-8")) if args.mappings else None
    report = build_knowledge_audit(baseline=baseline, mappings=mappings)
    output.mkdir(parents=True)
    (output / "MODEL_KNOWLEDGE_AUDIT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = [
        "# 模型能力知识库验收视图",
        "",
        "指标分别计数，不认证账号或作品质量。",
        "",
        "```json",
        json.dumps(report["metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "| 型号 | 修订 | 操作 | 已知／未知事实 | 实施与产品状态 |",
        "|---|---|---|---|---|",
    ]
    for model in report["models"]:
        rows.append(
            f"| {model['identity'][2]} | {model['identity'][3]} | "
            f"{', '.join(model['operations'])} | {model['claim_counts']} | "
            "未实施；不开放；账号未检查 |"
        )
    rows.extend(["", "所有未知、冲突和来源缺口均保留。原始修订与历史证据不改写。", ""])
    (output / "MODEL_KNOWLEDGE_AUDIT.md").write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
