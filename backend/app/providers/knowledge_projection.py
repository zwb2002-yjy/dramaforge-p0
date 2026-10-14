"""Read-only facts and evidence derived from typed revisions in the sole Catalog."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.providers.capability_manifest_v2 import TypedModelCapabilityManifest, TypedOperation
from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest
from app.providers.source_evidence import (
    ClaimStatus,
    SourceEvidenceStore,
    capability_claim_paths,
    evidence_override_paths,
    load_source_evidence,
    read_capability_pointer,
    resolve_field_evidence,
)


class KnowledgeFieldRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    claim_status: ClaimStatus
    source_snapshot_ref: str | None
    evidence_resolution: str
    blocker: str | None


class ModelKnowledgeRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    model_revision: str
    manifest_hash: str
    lifecycle: str
    operations: dict[str, TypedOperation]
    fields: list[KnowledgeFieldRead]
    claim_counts: dict[str, int]
    official_supported_fields: int
    unknown_bounds: int
    implementation_status: Literal["not_implemented"] = "not_implemented"
    product_open: Literal[False] = False
    account_status: Literal["not_checked"] = "not_checked"
    blockers: list[str] = Field(default_factory=lambda: ["MODEL_CONTRACT_NOT_TESTED", "NOT_ACTIVE"])


def project_model_knowledge(
    raw: dict[str, Any],
    *,
    store: SourceEvidenceStore | None = None,
) -> ModelKnowledgeRead:
    manifest = TypedModelCapabilityManifest.model_validate(raw)
    evidence = store if store is not None else load_source_evidence()
    fields: list[KnowledgeFieldRead] = []
    unknown_bounds = 0

    for path in capability_claim_paths(raw):
        node = read_capability_pointer(raw, path)
        result = resolve_field_evidence(
            raw,
            pointer=path,
            scope=manifest.source_scope(),
            claim_status=node["claim_status"],
            store=evidence,
        )
        fields.append(
            KnowledgeFieldRead(
                path=path,
                claim_status=result.claim_status,
                source_snapshot_ref=result.source_snapshot_ref,
                evidence_resolution=result.resolution,
                blocker=result.blocker,
            )
        )
        if node.get("kind") == "unknown":
            unknown_bounds += 1
    existing_paths = {field.path for field in fields}
    for pointer in evidence_override_paths(raw):
        if pointer in existing_paths:
            continue
        result = resolve_field_evidence(
            raw,
            pointer=pointer,
            scope=manifest.source_scope(),
            claim_status="unknown",
            store=evidence,
        )
        fields.append(
            KnowledgeFieldRead(
                path=pointer,
                claim_status=result.claim_status,
                source_snapshot_ref=result.source_snapshot_ref,
                evidence_resolution=result.resolution,
                blocker=result.blocker,
            )
        )
    blockers = sorted({field.blocker for field in fields if field.blocker})
    return ModelKnowledgeRead(
        model_revision=manifest.model_revision,
        manifest_hash=hash_manifest(raw),
        lifecycle=manifest.lifecycle,
        operations={str(key): value for key, value in manifest.operations.items()},
        fields=fields,
        claim_counts=dict(Counter(field.claim_status for field in fields)),
        official_supported_fields=sum(
            field.blocker is None and field.claim_status == "documented_supported"
            for field in fields
        ),
        unknown_bounds=unknown_bounds,
        blockers=["MODEL_CONTRACT_NOT_TESTED", "NOT_ACTIVE", *blockers],
    )


def knowledge_for_model(
    provider_type: str, protocol_profile: str, model_id: str
) -> ModelKnowledgeRead | None:
    candidates = [
        item
        for item in ModelCatalogLoader().load()
        if item.identity[:3] == (provider_type, protocol_profile, model_id)
        and item.as_dict().get("schema_version") == "2"
    ]
    if not candidates:
        return None
    # This is only a labelled knowledge view, never a Binding selection.
    chosen = max(candidates, key=lambda item: item.identity[3])
    return project_model_knowledge(chosen.as_dict())
