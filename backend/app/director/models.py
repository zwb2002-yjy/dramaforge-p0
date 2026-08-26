"""Persistence models for the controlled project-level Director workflow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
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


class DirectorWorkflowRun(Base):
    __tablename__ = "director_workflow_runs"
    __table_args__ = (UniqueConstraint("project_id", name="uq_director_workflow_project"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(String(80), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    current_artifact_versions: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CreativeArtifactVersion(Base):
    __tablename__ = "creative_artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "artifact_kind",
            "revision_no",
            name="uq_creative_artifact_kind_revision",
        ),
        UniqueConstraint(
            "project_id",
            "artifact_kind",
            "content_hash",
            name="uq_creative_artifact_kind_content",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    artifact_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("creative_artifact_versions.id", ondelete="RESTRICT"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BudgetAuthorization(Base):
    __tablename__ = "budget_authorizations"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_budget_auth_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    authorization_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    pricing_snapshot_id: Mapped[str] = mapped_column(String(160), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    consumed_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    authorized_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_approval_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    approval_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    approved_artifact_versions: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    budget_authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("budget_authorizations.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by_proposal_id: Mapped[UUID | None] = mapped_column(nullable=True)


class ChangeProposal(Base):
    __tablename__ = "change_proposals"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_change_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    target_artifact_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    base_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("creative_artifact_versions.id", ondelete="RESTRICT"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_confirmation")
    proposed_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImpactReport(Base):
    __tablename__ = "impact_reports"
    __table_args__ = (UniqueConstraint("change_proposal_id", name="uq_impact_report_proposal"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    change_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("change_proposals.id", ondelete="CASCADE"), nullable=False
    )
    invalidated_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_shot_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reusable_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    estimated_added_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    estimated_added_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkflowStepRun(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "idempotency_key", name="uq_step_run_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(80), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    input_version_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    output_version_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True
    )
    node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="RESTRICT"), nullable=True
    )
    service_run_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    trace_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DirectorIssue(Base):
    __tablename__ = "director_issues"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    responsible_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    suggested_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_version_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_step_runs.id", ondelete="SET NULL"), nullable=True
    )
    resolution: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductionBatch(Base):
    """Immutable authorization/creative snapshot for trial, production or repair."""

    __tablename__ = "production_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_batch_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    batch_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    budget_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("budget_authorizations.id", ondelete="RESTRICT"), nullable=False
    )
    locked_version_refs: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    selected_shot_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    template_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    quality_policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    semantic_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductionBatchShot(Base):
    __tablename__ = "production_batch_shots"
    __table_args__ = (
        UniqueConstraint("batch_id", "logical_shot_id", name="uq_batch_logical_shot"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False
    )
    logical_shot_id: Mapped[str] = mapped_column(String(40), nullable=False)
    shot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("shots.id", ondelete="RESTRICT"), nullable=True
    )
    graph_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    semantic_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    accepted_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    accepted_node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_budget_reservation_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False
    )
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("budget_authorizations.id", ondelete="RESTRICT"), nullable=False
    )
    node_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="reserved")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DirectorThread(Base):
    """Phase 7 Director Assistant conversation thread (03 §62).

    A thread is scoped to a project, scene or shot; one thread per scope.
    """

    __tablename__ = "director_threads"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_entity_id",
            name="uq_director_thread_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Director")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DirectorMessage(Base):
    """One Director Assistant message in a thread (03 §62)."""

    __tablename__ = "director_messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_threads.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
