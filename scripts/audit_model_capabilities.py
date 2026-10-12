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
import re
import subprocess
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
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


def pointer_value(payload: Any, path: str) -> Any:
    if not declared_path(payload, path):
        raise ValueError(f"undeclared JSON pointer: {path}")
    for token in path.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        payload = payload[token] if isinstance(payload, dict) else payload[int(token)]
    return payload


class _DocumentText(HTMLParser):
    """Static text extraction; embedded scripts are data, never executed."""

    ignored = frozenset({"script", "style", "nav", "header", "footer", "noscript"})
    void = frozenset({"br", "hr", "img", "input", "link", "meta", "source", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.void:
            self.stack.append((tag, tag in self.ignored))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not any(ignored for _, ignored in self.stack) and data.strip():
            self.parts.append(data.strip())


def extract_document(body: str) -> tuple[str, str, dict[str, Any]]:
    """Decode a cached document payload without evaluating JavaScript."""
    for match in re.finditer(r"window\._ROUTER_DATA\s*=\s*", body):
        try:
            router, _ = json.JSONDecoder().raw_decode(body[match.end() :])
        except ValueError:
            continue
        if not isinstance(router, dict) or not isinstance(router.get("loaderData"), dict):
            continue
        for page in router["loaderData"].values():
            doc = page.get("curDoc") if isinstance(page, dict) else None
            if not isinstance(doc, dict):
                continue
            markdown = doc.get("MDContent")
            if isinstance(markdown, str) and markdown.strip():
                return (
                    "router_markdown",
                    markdown,
                    {
                        "document_id": doc.get("DocumentID"),
                        "document_code": doc.get("DocumentCode"),
                        "library_code": doc.get("LibraryCode"),
                        "language": doc.get("Language"),
                        "title": doc.get("Title"),
                        "updated_at": doc.get("UpdatedTime"),
                    },
                )
    if not re.search(r"<(?:html|!doctype|body|script)\b", body, re.IGNORECASE):
        return "plain_text", body.strip(), {}
    parser = _DocumentText()
    parser.feed(body)
    return "html_text", "\n".join(parser.parts), {}


def inspect_cached_sources(
    checks: list[dict[str, Any]], bodies: Path
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    records: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    for check in checks:
        candidate = check["candidate_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", candidate):
            raise ValueError("invalid cached source candidate id")
        expected_id = hashlib.sha256(check["url"].encode()).hexdigest()
        if candidate != expected_id:
            raise ValueError("cached source id does not match URL")
        record = {
            "candidate_id": candidate,
            "url": check["url"],
            "checked_at": check.get("checked_at"),
            "response_body_sha256": check.get("body_sha256"),
            "extraction_status": "source_unavailable",
            "review_status": "unreviewed",
            "extracted_text_sha256": None,
        }
        path = bodies / f"{candidate}.html"
        if not path.resolve().is_relative_to(bodies.resolve()):
            raise ValueError("cached source path escapes the supplied body directory")
        if not path.is_file():
            records.append(record)
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("cached source exceeds the 10 MiB extraction bound")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != check.get("body_sha256"):
            raise ValueError("cached response body hash mismatch")
        body = raw.decode("utf-8-sig")
        kind, text, locator = extract_document(body)
        record.update(
            extraction_status="extracted_unreviewed" if text else "extraction_pending",
            extraction_format=kind,
            extracted_characters=len(text),
            locator=locator,
            extracted_text_sha256=hashlib.sha256(text.encode()).hexdigest() if text else None,
        )
        if text:
            texts[candidate] = text
        records.append(record)
    return records, texts


def atomic_facts(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """An enum is one claim value; its members are not separate coverage units."""
    if isinstance(value, dict) and value:
        for key, child in sorted(value.items()):
            yield from atomic_facts(child, f"{path}/{key.replace('~', '~0').replace('/', '~1')}")
    else:
        yield path or "/", value


def normalize_observations(
    observations: dict[str, Any], cached_sources: list[dict[str, Any]]
) -> dict[str, Any]:
    """Keep document assertions separate from exact-contract evidence status."""
    normalized = json.loads(json.dumps(observations))
    by_candidate = {record["candidate_id"]: record for record in cached_sources}
    source_refs = {
        source["id"]: source.get("source_candidate_ref")
        for source in normalized.get("source_observations", [])
    }
    groups = []
    for original in normalized.get("identified_official_claims", []):
        group = dict(original)
        group["source_text_status"] = group.pop("claim_status", "unknown")
        group["applicability_status"] = group.get("applicability_status", "unknown")
        # Phase 0 has no reviewed manifest evidence resolver. An observation,
        # even with a retained mapping, never grants executable support.
        group["contract_evidence_status"] = "unknown"
        group["implementation_verification"] = "not_verified_per_capability"
        group.pop("implementation", None)
        group["mapping_candidates"] = group.pop("schema_mapping", [])
        group["submitted_note"] = group.pop("blocker", None)
        group["blocker_codes"] = ["manifest_evidence_group_missing"]
        if group["applicability_status"] != "verified":
            group["blocker_codes"].append("source_applicability_unknown")
        cached = by_candidate.get(source_refs.get(group.get("source_ref")))
        group["source_extraction_status"] = cached["extraction_status"] if cached else "not_checked"
        if group["source_extraction_status"] != "extracted_unreviewed":
            group["blocker_codes"].append("source_text_not_extracted")
        if cached and cached["extraction_status"] == "extracted_unreviewed":
            group["source_locator"] = cached.get("locator", {})
            group["extracted_text_sha256"] = cached["extracted_text_sha256"]
        groups.append(group)
    normalized["identified_official_claims"] = groups
    return normalized


def identified_claims(
    observations: dict[str, Any], inventory: list[dict[str, Any]], repo: Path
) -> list[dict[str, Any]]:
    entries = {tuple(item["identity"]): item for item in inventory}
    result = []
    seen: set[str] = set()
    for group in observations.get("identified_official_claims", []):
        if group["id"] in seen:
            raise ValueError("duplicate identified claim group id")
        seen.add(group["id"])
        entry = entries.get(tuple(group["identity"]))
        raw = json.loads((repo / entry["path"]).read_text(encoding="utf-8")) if entry else {}
        typed = ModelCapabilityManifest.model_validate(raw).model_dump(mode="json") if entry else {}
        for value_path, value in atomic_facts(group.get("value")):
            pointers = group.get("mapping_by_value_path", {}).get(value_path, [])
            if isinstance(pointers, str):
                pointers = [pointers]
            matched = bool(pointers) and all(
                declared_path(typed, pointer)
                and declared_path(raw, pointer)
                and hash_manifest({"value": pointer_value(raw, pointer)})
                == hash_manifest({"value": value})
                for pointer in pointers
            )
            source_fact_status = group.get("source_fact_statuses", {}).get(value_path, "unknown")
            result.append(
                {
                    "id": f"{group['id']}{value_path}",
                    "group_id": group["id"],
                    "identity": group["identity"],
                    "in_initial_scope": bool(entry and entry["in_initial_scope"]),
                    "value_path": value_path,
                    "value": value,
                    "source_ref": group.get("source_ref"),
                    "source_text_status": source_fact_status,
                    "source_group_assertion": group["source_text_status"],
                    "applicability_status": group["applicability_status"],
                    "contract_evidence_status": group["contract_evidence_status"],
                    "schema_mapping": pointers,
                    "schema_mapping_status": "exact_value" if matched else "missing_or_mismatched",
                    "implementation_verification": "not_verified_per_capability",
                    "source_extraction_status": group["source_extraction_status"],
                    "blocker_codes": group["blocker_codes"],
                }
            )
    return result


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


def build_audit(
    repo: Path,
    *,
    source_sha: str,
    checked_at: str,
    observations: dict[str, Any] | None = None,
    cached_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    declarations_by_field: list[dict[str, Any]] = []
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
            declarations_by_field.append(
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
                    "model_declaration_ref": list(key),
                    "implementation_verification": "not_verified_per_capability",
                    "product_open": item["product_open"],
                    "blocker": blockers,
                }
            )
    scoped = [item for item in inventory if item["in_initial_scope"]]
    scoped_fields = [item for item in declarations_by_field if item["in_initial_scope"]]
    normalized = normalize_observations(observations or {}, cached_sources or [])
    claims = identified_claims(normalized, inventory, repo)
    scoped_claims = [item for item in claims if item["in_initial_scope"]]
    active = [item for item in scoped if item["publication_lifecycle"] == "active"]
    frozen = [
        {"identity": item["identity"], "manifest_hash": item["manifest_hash"]} for item in inventory
    ]
    return {
        "audit_schema_version": 2,
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
                "outside_frozen_inventory": [
                    i["id"]
                    for i in claims
                    if tuple(i["identity"]) not in {tuple(entry["identity"]) for entry in inventory}
                ],
                "unit": "identified_official_fact; enums are one value",
                "source_text_counts": dict(Counter(i["source_text_status"] for i in scoped_claims)),
                "exact_contract_evidence_counts": dict(
                    Counter(i["contract_evidence_status"] for i in scoped_claims)
                ),
            },
            "structured_mapping": {
                "total": len(scoped_claims),
                "mapped_exact_value": sum(
                    i["schema_mapping_status"] == "exact_value" for i in scoped_claims
                ),
                "missing_or_mismatched": sum(
                    i["schema_mapping_status"] != "exact_value" for i in scoped_claims
                ),
                "ratio": sum(i["schema_mapping_status"] == "exact_value" for i in scoped_claims)
                / len(scoped_claims)
                if scoped_claims
                else None,
                "status": "measured_from_identified_facts"
                if scoped_claims
                else "no_identified_official_facts",
            },
            "catalog_field_retention": {
                "total_raw_leaves": len(scoped_fields),
                "retained_by_typed_reader": sum(
                    i["representation"] == "structured" for i in scoped_fields
                ),
                "legacy_json": sum(i["representation"] == "legacy_json" for i in scoped_fields),
                "string_features": sum(
                    i["representation"] == "string_feature" for i in scoped_fields
                ),
                "unmapped_schema_fields": sum(
                    i["representation"] == "unmapped_schema_field" for i in scoped_fields
                ),
                "status": "field_retention_only_not_capability_coverage",
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
        "catalog_declarations": declarations_by_field,
        "official_claims": claims,
        "manual_observations": normalized,
        "cached_sources": cached_sources or [],
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
    lines.extend(
        [
            "",
            "## 已识别官方事实与映射",
            "",
            "来源原文陈述、精确合同适用性、合同证据与实施验证分别记录。",
            "",
            "| Fact | 原文 | 适用性 | 合同证据 | 映射 |",
            "|---|---|---|---|---|",
        ]
    )
    for claim in report["official_claims"]:
        lines.append(
            f"| {claim['id']} | {claim['source_text_status']} | "
            f"{claim['applicability_status']} | {claim['contract_evidence_status']} | "
            f"{claim['schema_mapping_status']} |"
        )
    lines.extend(["", "## 缓存来源正文（不授予能力支持）", ""])
    for source in report["cached_sources"]:
        lines.append(
            f"- {source['candidate_id']}: {source['extraction_status']}; "
            f"{source.get('extracted_characters', 0)} characters; "
            f"text hash={source['extracted_text_sha256']}"
        )
    lines.extend(["", "## 局限", "", *[f"- {item}" for item in report["limitations"]], ""])
    return "\n".join(lines)


def write_reports(
    repo: Path,
    output: Path,
    report: dict[str, Any],
    *,
    extracted_texts: dict[str, str] | None = None,
) -> None:
    repo, output = repo.resolve(), output.resolve()
    if not output.is_relative_to(repo / "tmp"):
        raise ValueError(
            "audit output must be inside repository tmp/ (never the catalog/docs source)"
        )
    if any((output / name).exists() for name in REPORT_NAMES):
        raise ValueError("frozen report already exists; choose a new evidence directory")
    observations = report["manual_observations"]
    contents = {
        REPORT_NAMES[0]: json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        REPORT_NAMES[1]: coverage_markdown(report),
    }
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
        contents[name] = content + "\n"
    for candidate, text in (extracted_texts or {}).items():
        if not re.fullmatch(r"[0-9a-f]{64}", candidate):
            raise ValueError("invalid extracted source id")
        contents[f"source-texts/{candidate}.md"] = text
    # Render/validate before creating the destination: bad observations must
    # not leave a partial frozen report that cannot be rerun.
    output.mkdir(parents=True, exist_ok=True)
    for name, content in contents.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as file:
            file.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--source-checks", type=Path)
    parser.add_argument("--source-bodies", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    sha = subprocess.run(
        ["git", "-C", str(args.repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if bool(args.source_checks) != bool(args.source_bodies):
        parser.error("--source-checks and --source-bodies must be provided together")
    observations = (
        json.loads(args.observations.read_text(encoding="utf-8-sig")) if args.observations else {}
    )
    cached, extracted_texts = (
        inspect_cached_sources(
            json.loads(args.source_checks.read_text(encoding="utf-8-sig")), args.source_bodies
        )
        if args.source_checks
        else ([], {})
    )
    report = build_audit(
        args.repo_root,
        source_sha=sha,
        checked_at=datetime.now(UTC).isoformat(),
        observations=observations,
        cached_sources=cached,
    )
    report["source_worktree_status"] = subprocess.run(
        ["git", "-C", str(args.repo_root), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        report["inventory_diff"] = compare_inventory(previous, report)
    write_reports(args.repo_root, args.output_dir, report, extracted_texts=extracted_texts)
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
