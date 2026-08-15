"""Execution-layer models field-faithful to `04` (graph_nodes/node_runs/artifacts/ops).

RLS policies land in S1-RLS-0.1. Product path must use Worker, not request-thread spike.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base

_node_type = Enum(
    "prompt_compose",
    "keyframe",
    "identity_review",
    "video",
    "video_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
    "export",
    name="node_type",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_node_run_status = Enum(
    "queued",
    "running",
    "cancel_requested",
    "cached",
    "blocked_budget",
    "completed",
    "completed_after_cancel",
    "failed",
    "cancelled",
    name="node_run_status",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_artifact_type = Enum(
    "image",
    "video",
    "audio",
    "subtitle",
    "timeline",
    "export_package",
    "document",
    name="artifact_type",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_artifact_state = Enum(
    "quarantined",
    "available",
    "cold",
    "delete_requested",
    "deleted",
    name="artifact_state",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_provider_purpose = Enum(
    "primary",
    "schema_repair",
    "transport_retry",
    "provider_fallback",
    name="provider_operation_purpose",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_provider_status = Enum(
    "created",
    "submission_started",
    "submitted",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "timed_out",
    "unknown_submission",
    "rejected",
    name="provider_operation_status",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("graph_version_id", "node_key", name="uq_graph_nodes_version_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(120), nullable=False)
    node_type: Mapped[str] = mapped_column(
        _node_type.with_variant(String(40), "sqlite"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    cacheable: Mapped[bool] = mapped_column(nullable=False, default=True)
    latest_successful_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "graph_version_id",
            "upstream_node_id",
            "output_port",
            "downstream_node_id",
            "input_port",
            "position",
            name="uq_graph_edges_identity",
        ),
        UniqueConstraint(
            "graph_version_id",
            "downstream_node_id",
            "input_port",
            "position",
            name="uq_graph_edges_input_position",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="CASCADE"), nullable=False
    )
    upstream_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    output_port: Mapped[str] = mapped_column(String(80), nullable=False)
    downstream_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    input_port: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "content_hash",
            "artifact_type",
            name="uq_artifacts_project_hash_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(
        _artifact_type.with_variant(String(40), "sqlite"), nullable=False
    )
    storage_state: Mapped[str] = mapped_column(
        _artifact_state.with_variant(String(32), "sqlite"),
        nullable=False,
        default="quarantined",
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    produced_by_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NodeRun(Base):
    __tablename__ = "node_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_node_runs_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="RESTRICT"), nullable=False
    )
    graph_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    production_batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    budget_reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("budget_reservations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        _node_run_status.with_variant(String(40), "sqlite"),
        nullable=False,
        default="queued",
    )
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    platform_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    avoided_cost_estimate: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    result_artifact_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reused_from_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShotHumanLock(Base):
    """Durable human lock for a shot — blocks Agent/quick overwrite rework."""

    __tablename__ = "shot_human_locks"
    __table_args__ = (UniqueConstraint("project_id", "shot_id", name="uq_shot_lock"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(nullable=False)
    locked: Mapped[bool] = mapped_column(nullable=False, default=True)
    locked_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderOperation(Base):
    __tablename__ = "provider_operations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="CASCADE"), nullable=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    purpose: Mapped[str] = mapped_column(
        _provider_purpose.with_variant(String(40), "sqlite"),
        nullable=False,
        default="primary",
    )
    operation_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    actual_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_model: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_operation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote_secondary_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    protocol_profile: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stage A+B: persisted execution provenance + resume context. Resume is
    # driven by these snapshots, never by current Feature Flags or Project
    # bindings. All snapshots are immutable once submission starts.
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    model_binding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_model_bindings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    catalog_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_model_catalog_entries.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    capability_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selection_plan: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    resume_token: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    execution_path_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        _provider_status.with_variant(String(40), "sqlite"),
        nullable=False,
        default="created",
    )
    request_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    response_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    token_usage: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
