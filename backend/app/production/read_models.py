"""Read-only production projections; requests never authorize execution."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NodeRunRead(BaseModel):
    id: UUID
    attempt_no: int
    status: str
    node_key: str
    input_hash: str
    result_artifact_id: UUID | None
    provider_cost: str
    output_summary: dict[str, object]
    input_snapshot: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    upstream_dependencies: list[UpstreamDependencyRead] = Field(default_factory=list)


class UpstreamDependencyRead(BaseModel):
    node_key: str
    run_id: UUID | None
    status: str
    result_artifact_id: UUID | None


class ArtifactRead(BaseModel):
    id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    mime_type: str
    storage_state: str
    produced_by_run_id: UUID | None
    width: int | None
    height: int | None
    duration_seconds: str | None


class ProviderOperationRead(BaseModel):
    id: UUID
    node_run_id: UUID | None
    operation_kind: str
    actual_provider: str
    actual_model: str
    provider_request_id: str | None
    protocol_profile: str | None
    status: str
    request_fingerprint: str
    request_summary: dict[str, object]
    response_summary: dict[str, object]
    model_binding_id: UUID | None
    catalog_entry_id: UUID | None
    capability_manifest_hash: str | None
    connection_id: UUID | None
    provider_connection_revision_id: UUID | None
    credential_revision_id: UUID | None
    execution_path_version: str | None
    provider_cost: str | None
    currency: str
    submitted_at: str | None
    completed_at: str | None


class ProjectSnapshot(BaseModel):
    project_id: UUID
    name: str
    node_runs: list[NodeRunRead]
    artifacts: list[ArtifactRead]
    provider_operations: list[ProviderOperationRead]


class ProductionRunStatusRead(BaseModel):
    id: UUID
    status: str
    result_artifact_id: UUID | None
    error_code: str | None


class ProductionRunHistoryRead(ProductionRunStatusRead):
    node_key: str
    attempt_no: int
    shot_id: str | None
    execution_branch: str
    experiment_id: str | None
    created_at: datetime
    error_code: str | None
    error_summary: str | None


class ProductionStageRead(BaseModel):
    """Effective mainline attempts, never an inferred Formal or approval state."""

    node_key: str
    status_counts: dict[str, int]
    latest_failure: ProductionRunHistoryRead | None


class ProductionSummaryRead(BaseModel):
    project_id: UUID
    total_runs: int
    completed_runs: int
    running_runs: int
    failed_runs: int
    artifact_count: int
    recent_failures: list[ProductionRunHistoryRead]
    has_more_failures: bool
    stages: list[ProductionStageRead]


class ProductionRunPage(BaseModel):
    items: list[ProductionRunHistoryRead]
    next_cursor: str | None


class ProductionArtifactPage(BaseModel):
    items: list[ArtifactRead]
    next_cursor: str | None
