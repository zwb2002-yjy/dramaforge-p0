"""Execution-layer models (NodeRun, ProviderOperation, Artifact) for local S2+ paths.

Field names/types mirror `04` for columns this slice uses. Full RLS/triggers remain PG-only.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
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
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    cacheable: Mapped[bool] = mapped_column(nullable=False, default=True)
    latest_successful_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
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
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_state: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    produced_by_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
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
    parent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ProviderOperation(Base):
    __tablename__ = "provider_operations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="CASCADE"), nullable=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="primary")
    operation_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    actual_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_model: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_operation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    request_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    response_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    provider_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
