"""Creation-domain models field-faithful to `04` (briefs/plans/authorizations)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base

_creation_plan_status = Enum(
    "draft",
    "awaiting_confirmation",
    "confirmed",
    "superseded",
    "cancelled",
    name="creation_plan_status",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_creative_revision_source = Enum(
    "user",
    "agent",
    "imported",
    name="creative_revision_source",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_agent_operation = Enum(
    "draft_brief",
    "refine_brief",
    "draft_plan",
    "skill_execute",
    "director_assist",
    name="agent_operation",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)
_agent_run_status = Enum(
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "stale",
    "cancelled",
    name="agent_run_status",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)


class CreativeBrief(Base):
    __tablename__ = "creative_briefs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
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


class CreativeBriefRevision(Base):
    __tablename__ = "creative_brief_revisions"
    __table_args__ = (
        UniqueConstraint("creative_brief_id", "revision_no", name="uq_brief_rev_no"),
        UniqueConstraint("id", "project_id", name="uq_brief_rev_id_project"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    creative_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey("creative_briefs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_kind: Mapped[str] = mapped_column(
        _creative_revision_source.with_variant(String(16), "sqlite"), nullable=False
    )
    source_agent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    brief: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        _creation_plan_status.with_variant(String(32), "sqlite"),
        nullable=False,
        default="draft",
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreationPlan(Base):
    __tablename__ = "creation_plans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_agent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_brief_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("creative_brief_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    plan: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    context_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    materialization_schema_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="materialization-p0-v1"
    )
    status: Mapped[str] = mapped_column(
        _creation_plan_status.with_variant(String(32), "sqlite"),
        nullable=False,
        default="draft",
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    materialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PlanningAuthorization(Base):
    __tablename__ = "planning_authorizations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    pricing_snapshot_id: Mapped[str] = mapped_column(String(120), nullable=False)
    authorized_operations: Mapped[list[str]] = mapped_column(
        ARRAY(_agent_operation).with_variant(JSON(), "sqlite"), nullable=False
    )
    estimated_max_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRun(Base):
    """AgentRun shell; full claim/lease semantics land with S2-RUNTIME."""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    initiated_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    planning_authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("planning_authorizations.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    operation: Mapped[str] = mapped_column(
        _agent_operation.with_variant(String(40), "sqlite"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        _agent_run_status.with_variant(String(32), "sqlite"),
        nullable=False,
        default="queued",
    )
    target_brief_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    target_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    requested_capability: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    context_compiler_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    external_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stable_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_brief_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    result_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
