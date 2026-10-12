#!/usr/bin/env python3
"""Offline catalog baseline audit; never changes capability or runtime state.

Run with the repository's backend environment and PYTHONPATH=backend. Reports
are disposable evidence under tmp/, not a second catalog. URLs are recorded,
never fetched. A fixture or a source URL cannot establish official support.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest
from app.providers.manifest import ModelCapabilityManifest

INITIAL_PROVIDERS = frozenset({"agnes", "minimax", "volcengine"})
IDENTITY_FIELDS = ("provider_type", "protocol_profile", "model_id", "model_revision")
REPORT_NAMES = (
    "MODEL_CAPABILITY_COVERAGE_AUDIT.json",
    "MODEL_CAPABILITY_COVERAGE_AUDIT.md",
    "MODEL_DELETION_INVARIANT_AUDIT.md",
    "MODEL_BASELINE_AUDIT.md",
)


def identity(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(payload[field] for field in IDENTITY_FIELDS)


def leaves(value: Any, path: str) -> Iterator[tuple[str, Any]]:
    """RFC 6901 paths preserve dots/slashes in operation and contract IDs."""
    if isinstance(value, dict) and value:
        for key, child in sorted(value.items()):
            token = key.replace("~", "~0").replace("/", "~1")
            yield from leaves(child, f"{path}/{token}")
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaves(child, f"{path}/{index}")
    else:
        # Empty declarations and explicit nulls must not disappear from audits.
        yield path, value


def declared_path(payload: Any, path: str) -> bool:
    """Only fields retained by the typed reader qualify as schema mappings."""
    for token in path.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(payload, dict) and token in payload:
            payload = payload[token]
        elif isinstance(payload, list) and token.isdigit() and int(token) < len(payload):
            payload = payload[int(token)]
        else:
            return False
    return True


def annotation_urls(path: Path) -> dict[str, str]:
    """Read the existing advisory URL map without importing application state."""
    constants: dict[str, Any] = {}
    if not path.exists():
        return {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Dict):
            values: dict[str, str] = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    resolved = (
                        constants.get(value.id)
                        if isinstance(value, ast.Name)
                        else value.value
                        if isinstance(value, ast.Constant)
                        else None
                    )
                    if isinstance(resolved, str):
                        values[key.value] = resolved
            constants[target.id] = values
        elif isinstance(node.value, ast.Constant):
            constants[target.id] = node.value.value
    return constants.get("_SOURCES", {})


def build_audit(repo: Path, *, source_sha: str, checked_at: str) -> dict[str, Any]:
    catalog = repo / "backend/app/providers/model_catalog"
    fixture_root = repo / "fixtures/providers/contracts"
    fixtures: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for path in sorted(fixture_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = identity(payload["manifest"])
        fixtures.setdefault(key, []).append({"path": path, "payload": payload})
    annotations = annotation_urls(repo / "backend/app/providers/capability_sources.py")
    inventory: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    claims: list[dict[str, Any]] = []
    for loaded in ModelCatalogLoader(catalog).load():
        raw = loaded.as_dict()
        typed = ModelCapabilityManifest.model_validate(raw).model_dump(
            mode="json", exclude_unset=True
        )
        key = loaded.identity
        exact_fixtures = fixtures.get(key, [])
        valid_fixtures = [
            item
            for item in exact_fixtures
            if item["payload"]["manifest"] == raw
            and item["payload"].get("manifest_hash") == loaded.manifest_hash
        ]
        declarations = [
            {
                "url": evidence["source_url"],
                "association": "manifest_evidence",
                "kind": evidence["source_type"],
                "declared_checked_at": evidence["checked_at"],
            }
            for evidence in raw.get("evidence", {}).values()
        ]
        advisory = annotations.get(f"{key[0]}/{key[2]}")
        if advisory:
            declarations.append(
                {"url": advisory, "association": "advisory_annotation", "kind": "advisory_only"}
            )
        for fixture in valid_fixtures:
            doc = fixture["payload"].get("contract", {}).get("documentation_source", {})
            if doc.get("url"):
                declarations.append(
                    {
                        "url": doc["url"],
                        "association": "fixture_documentation",
                        "kind": "unreviewed_fixture_annotation",
                    }
                )
        urls = sorted({item["url"] for item in declarations if item["url"].startswith("https://")})
        source_refs = [hashlib.sha256(url.encode()).hexdigest() for url in urls]
        for declaration in declarations:
            url = declaration["url"]
            if not url.startswith("https://"):
                continue
            source = sources.setdefault(
                url,
                {
                    "candidate_id": hashlib.sha256(url.encode()).hexdigest(),
                    "url": url,
                    "associations": [],
                    "retrieval_status": "not_checked",
                    "content_sha256": None,
                },
            )
            association = {
                "identity": list(key),
                **{k: v for k, v in declaration.items() if k != "url"},
            }
            if association not in source["associations"]:
                source["associations"].append(association)
        in_scope = key[0] in INITIAL_PROVIDERS
        item = {
            "identity": list(key),
            "path": loaded.source_path.relative_to(repo).as_posix(),
            "file_sha256": hashlib.sha256(loaded.source_path.read_bytes()).hexdigest(),
            "manifest_hash": loaded.manifest_hash,
            "publication_lifecycle": loaded.publication_lifecycle,
            "implementation_declaration": raw["implementation_status"],
            "catalog_source": raw.get("catalog_source", "official_static"),
            "in_initial_scope": in_scope,
            "operations": sorted(raw["operations"]),
            "source_candidate_refs": source_refs,
            "exact_fixture_paths": [f["path"].relative_to(repo).as_posix() for f in valid_fixtures],
            "fixture_status": "exact_match" if len(valid_fixtures) == 1 else "missing_or_ambiguous",
            "compiler_test_status": "not_run_by_audit",
            "product_open": "not_verified_by_offline_inventory",
            "account_availability": "not_checked_by_offline_inventory",
        }
        inventory.append(item)
        semantic = {"operations": raw["operations"], "option_schema": raw.get("option_schema", {})}
        if raw.get("documented_features"):
            semantic["documented_features"] = raw["documented_features"]
        for claim_path, value in leaves(semantic, ""):
            legacy = "output_constraints" in claim_path.split("/")
            feature = claim_path.startswith("/documented_features/")
            mapped = declared_path(typed, claim_path)
            representation = (
                "string_feature"
                if feature
                else "legacy_json"
                if legacy
                else "unmapped_schema_field"
                if not mapped
                else "structured"
            )
            blockers = ["official_evidence_gap"]
            if loaded.publication_lifecycle != "active":
                blockers.append("not_active")
            if representation != "structured":
                blockers.append("typed_contract_mapping_pending")
            if value is None and claim_path.endswith(
                ("/maximum", "/maximum_total_references", "/max_bytes")
            ):
                blockers.append("unknown_unlimited_not_distinguished")
            claims.append(
                {
                    "identity": list(key),
                    "in_initial_scope": in_scope,
                    "claim_path": claim_path,
                    "value": value,
                    "schema_path": claim_path if mapped and not feature else None,
                    "representation": representation,
                    "claim_status": "unknown",
                    "evidence_resolution": "missing_reviewed_group",
                    "source_snapshot_ref": None,
                    "implementation": raw["implementation_status"],
                    "compiler_fixture": item["exact_fixture_paths"],
                    "product_open": item["product_open"],
                    "blocker": blockers,
                }
            )
    scoped = [item for item in inventory if item["in_initial_scope"]]
    scoped_claims = [item for item in claims if item["in_initial_scope"]]
    active = [item for item in scoped if item["publication_lifecycle"] == "active"]
    frozen = [
        {"identity": item["identity"], "manifest_hash": item["manifest_hash"]} for item in inventory
    ]
    return {
        "audit_schema_version": 1,
        "source_sha": source_sha,
        "checked_at": checked_at,
        "inventory_sha256": hash_manifest({"inventory": frozen}),
        "scope": {
            "initial_providers": sorted(INITIAL_PROVIDERS),
            "definition": (
                "Packaged catalog only; DB-only legacy revisions require "
                "a separate read-only observation."
            ),
        },
        "metrics": {
            "inventory": {
                "all_revisions": len(inventory),
                "initial_scope_revisions": len(scoped),
                "initial_scope_models": len({tuple(i["identity"][:3]) for i in scoped}),
                "with_url_candidate": sum(bool(i["source_candidate_refs"]) for i in scoped),
                "reviewed_applicable_sources": 0,
            },
            "claim_classification": {
                "total": len(scoped_claims),
                "counts": dict(Counter(i["claim_status"] for i in scoped_claims)),
            },
            "structured_mapping": {
                "total": len(scoped_claims),
                "structured": sum(i["representation"] == "structured" for i in scoped_claims),
                "legacy_json": sum(i["representation"] == "legacy_json" for i in scoped_claims),
                "string_features": sum(
                    i["representation"] == "string_feature" for i in scoped_claims
                ),
                "unmapped_schema_fields": sum(
                    i["representation"] == "unmapped_schema_field" for i in scoped_claims
                ),
            },
            "official_evidence": {
                "reviewed_supported_claims": 0,
                "candidate_claims": len(scoped_claims),
                "reason": "Existing URLs/fixtures do not provide reviewed subtree coverage.",
            },
            "compiler_contracts": {
                "active_contracts": len(active),
                "with_exact_fixture": sum(i["fixture_status"] == "exact_match" for i in active),
                "passed_by_this_audit": None,
                "status": "tests_must_be_reported_separately",
            },
            "product_open": {"verified_contracts": None, "status": "not_verified"},
        },
        "inventory": inventory,
        "claims": claims,
        "source_candidates": list(sources.values()),
        "limitations": [
            (
                "unknown is the audit evidence classification; it does not rewrite or disable "
                "the frozen runtime contract."
            ),
            (
                "All catalog declarations are enumerated; provider documentation extraction "
                "is not complete."
            ),
            "No network, database, credentials, Provider create, poll or recovery is performed.",
            "Fixture equality is measured independently from executed Compiler and negative tests.",
        ],
    }


def compare_inventory(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    old = {tuple(i["identity"]): i["manifest_hash"] for i in previous["inventory"]}
    new = {tuple(i["identity"]): i["manifest_hash"] for i in current["inventory"]}
    return {
        "added": [list(key) for key in sorted(new.keys() - old.keys())],
        "removed": [list(key) for key in sorted(old.keys() - new.keys())],
        "changed_existing_revision": [
            list(key) for key in sorted(old.keys() & new.keys()) if old[key] != new[key]
        ],
    }


def coverage_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 模型能力覆盖审计（阶段 0）",
        "",
        f"Source SHA: `{report['source_sha']}`",
        f"检查时间: {report['checked_at']}",
        "",
        "## 独立指标",
        "",
        "URL 候选不是已审核证据；exact fixture 不是已执行 Compiler 测试；unknown 不改写运行时。",
        "",
        "```json",
        json.dumps(report["metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 冻结目录",
        "",
        "| Provider / Protocol / Model / Revision | 状态 | 范围 | Fixture |",
        "|---|---|---|---|",
    ]
    for item in report["inventory"]:
        lines.append(
            f"| {' / '.join(item['identity'])} | {item['publication_lifecycle']} | "
            f"{'首批' if item['in_initial_scope'] else '上下文'} | {item['fixture_status']} |"
        )
    lines.extend(["", "## 来源候选（不自动继承能力）", ""])
    for source in report["source_candidates"]:
        lines.append(
            f"- [{source['url']}]({source['url']}): "
            f"{len(source['associations'])} 个显式目录关联；未自动抓取/审核。"
        )
    lines.extend(["", "## 局限", "", *[f"- {item}" for item in report["limitations"]], ""])
    return "\n".join(lines)


def write_reports(
    repo: Path, output: Path, report: dict[str, Any], observations: dict[str, Any]
) -> None:
    repo, output = repo.resolve(), output.resolve()
    if not output.is_relative_to(repo / "tmp"):
        raise ValueError(
            "audit output must be inside repository tmp/ (never the catalog/docs source)"
        )
    if any((output / name).exists() for name in REPORT_NAMES):
        raise ValueError("frozen report already exists; choose a new evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    # Observations remain attributed external evidence. They never grant a claim
    # support status or change any computed metric/manifest in the audit.
    report = {**report, "manual_observations": observations}
    (output / REPORT_NAMES[0]).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / REPORT_NAMES[1]).write_text(coverage_markdown(report), encoding="utf-8")
    for name, section in ((REPORT_NAMES[2], "invariants"), (REPORT_NAMES[3], "baseline")):
        payload = observations.get(
            section, {"status": "not_verified", "reason": "No reviewed observations supplied."}
        )
        title = "误删不变量审计" if section == "invariants" else "基线与阶段 1 输入"
        content = f"# {title}（阶段 0）\n\nSource SHA: `{report['source_sha']}`\n\n"
        content += "以下是单独核验的观察记录；未核验不得视为等价替代或正式验收。\n\n"
        if section == "invariants" and isinstance(payload, list):
            content += "| 不变量 | 分类 | 核验状态 | 结论 / 下一阶段 |\n|---|---|---|---|\n"
            for item in payload:
                content += (
                    f"| {item['id']} {item['name']} | {item['classification']} | "
                    f"{item['verification']} | {item['finding']} |\n"
                )
            for item in payload:
                content += f"\n## {item['id']} {item['name']}\n\n{item['finding']}\n\n"
                content += "\n".join(f"- `{ref}`" for ref in item.get("evidence", [])) + "\n"
                if item.get("next_step"):
                    content += f"\n下一步：{item['next_step']}\n"
        elif section == "baseline" and isinstance(payload, dict):
            for key, value in payload.items():
                content += f"\n## {key}\n\n"
                if isinstance(value, str):
                    content += value + "\n"
                else:
                    content += (
                        "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n"
                    )
        else:
            content += "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```\n"
        (output / name).write_text(content + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    sha = subprocess.run(
        ["git", "-C", str(args.repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = build_audit(args.repo_root, source_sha=sha, checked_at=datetime.now(UTC).isoformat())
    report["source_worktree_status"] = subprocess.run(
        ["git", "-C", str(args.repo_root), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        report["inventory_diff"] = compare_inventory(previous, report)
    observations = (
        json.loads(args.observations.read_text(encoding="utf-8-sig")) if args.observations else {}
    )
    write_reports(args.repo_root, args.output_dir, report, observations)
    print(
        json.dumps(
            {
                "source_sha": sha,
                "inventory_sha256": report["inventory_sha256"],
                "metrics": report["metrics"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if report.get("inventory_diff", {}).get("changed_existing_revision") else 0


if __name__ == "__main__":
    raise SystemExit(main())
