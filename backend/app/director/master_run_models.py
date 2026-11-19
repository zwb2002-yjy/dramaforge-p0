"""Continuous-goal MasterRun, immutable plans and control receipts (M02).

A MasterRun is one durable creative goal bound to its originating Agent Turn.
It is not a second Agent runtime and never replaces DirectorTurn, NodeRun,
ProviderOperation or Artifact facts: it records the goal, the accepted plan and
the user's control decisions, while execution evidence stays in the existing
records.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT

MASTER_RUN_STATUSES = (
    "planning",
    "running",
    "waiting",
    "paused",
    "stopping",
    "succeeded",
    "failed",
    "cancelled",
)
MASTER_RUN_DESIRED_STATES = ("run", "pause", "cancel")
MASTER_RUN_CONTROL_OPERATIONS = ("pause", "resume", "cancel", "verify")
_TERMINAL = "('succeeded','failed','cancelled')"


class DirectorMasterRun(Base):
    """One continuous creative goal originated by a real Agent Turn."""

    __tablename__ = "director_master_runs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_master_run_scope"),
        UniqueConstraint(
            "id", "project_id", "workspace_id", "actor_id", name="uq_master_run_owner",
        ),
        UniqueConstraint("project_id", "origin_turn_id", name="uq_master_run_origin"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"], ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_master_run_project_scope",
        ),
        ForeignKeyConstraint(
            ["source_thread_id", "project_id"],
            ["director_threads.id", "director_threads.project_id"],
            ondelete="NO ACTION", name="fk_master_run_thread_scope",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["origin_turn_id", "project_id", "workspace_id", "actor_id",
             "source_thread_id", "origin_turn_kind"],
            ["director_turns.id", "director_turns.project_id", "director_turns.workspace_id",
             "director_turns.actor_id", "director_turns.thread_id", "director_turns.turn_kind"],
            ondelete="NO ACTION", name="fk_master_run_origin_turn",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint(
            "origin_turn_kind = 'agent'", name="ck_master_run_origin_kind",
        ),
        CheckConstraint(
            "length(trim(goal)) >= 1 AND length(goal) <= 16000", name="ck_master_run_goal",
        ),
        CheckConstraint("control_epoch >= 0", name="ck_master_run_control_epoch"),
        CheckConstraint("revision > 0", name="ck_master_run_revision"),
        CheckConstraint(
            "status IN ('planning','running','waiting','paused','stopping',"
            "'succeeded','failed','cancelled')",
            name="ck_master_run_status",
        ),
        CheckConstraint(
            "desired_state IN ('run','pause','cancel')", name="ck_master_run_desired_state",
        ),
        CheckConstraint(
            f"(status IN {_TERMINAL}) = (finished_at IS NOT NULL)",
            name="ck_master_run_finished",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_master_run_finished_after_create",
        ),
        CheckConstraint(
            "deadline_at IS NULL OR deadline_at >= created_at",
            name="ck_master_run_deadline_after_create",
        ),
        CheckConstraint(
            f"archived_at IS NULL OR (status IN {_TERMINAL} AND finished_at IS NOT NULL "
            "AND archived_at >= finished_at)",
            name="ck_master_run_archive_terminal",
        ),
        # Run <-> Plan is a deliberate cycle: both sides must be able to point at
        # the other's accepted snapshot. PostgreSQL creates this with ALTER (AFTER
        # the plan table exists); the portable unit database omits it.
        ForeignKeyConstraint(
            ["current_plan_id", "id", "project_id"],
            ["director_master_run_plans.id", "director_master_run_plans.master_run_id",
             "director_master_run_plans.project_id"],
            name="fk_master_run_current_plan", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED", use_alter=True,
        ).ddl_if(dialect="postgresql"),
        Index("ix_master_run_status", "project_id", "status", "updated_at", "id"),
        Index("ix_master_run_thread", "source_thread_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    source_thread_id: Mapped[UUID] = mapped_column(nullable=False)
    origin_turn_id: Mapped[UUID] = mapped_column(nullable=False)
    origin_turn_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="agent", server_default="agent",
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    current_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="planning", server_default="planning",
    )
    desired_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="run", server_default="run",
    )
    wait_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    control_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class DirectorMasterRunPlan(Base):
    """Immutable accepted-plan snapshot; deduplicated by run and content hash."""

    __tablename__ = "director_master_run_plans"
    __table_args__ = (
        UniqueConstraint("master_run_id", "revision", name="uq_master_run_plan_revision"),
        UniqueConstraint("master_run_id", "plan_hash", name="uq_master_run_plan_hash"),
        UniqueConstraint(
            "id", "master_run_id", "project_id", name="uq_master_run_plan_scope",
        ),
        UniqueConstraint(
            "master_run_id", "revision", "project_id", name="uq_master_run_plan_revision_scope",
        ),
        UniqueConstraint(
            "id", "revision", "master_run_id", "project_id",
            name="uq_master_run_plan_revision_identity",
        ),
        UniqueConstraint("project_id", "decision_ref", name="uq_master_run_plan_decision"),
        ForeignKeyConstraint(
            ["master_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            ondelete="NO ACTION", name="fk_master_run_plan_run",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["decision_ref", "project_id"],
            ["director_proposal_items.id", "director_proposal_items.project_id"],
            ondelete="NO ACTION", name="fk_master_run_plan_decision",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_turn_id", "master_run_id", "project_id"],
            ["director_turns.id", "director_turns.master_run_id", "director_turns.project_id"],
            ondelete="NO ACTION", name="fk_master_run_plan_turn",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("revision > 0", name="ck_master_run_plan_revision"),
        Index("ix_master_run_plan_run", "project_id", "master_run_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    master_run_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    plan_data: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    decision_ref: Mapped[UUID] = mapped_column(nullable=False)
    created_by_turn_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class DirectorMasterRunControlReceipt(Base):
    """Immutable receipt for one control decision on one run revision."""

    __tablename__ = "director_master_run_control_receipts"
    __table_args__ = (
        UniqueConstraint(
            "master_run_id", "expected_revision", "operation",
            name="uq_master_run_receipt_key",
        ),
        ForeignKeyConstraint(
            ["master_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            ondelete="NO ACTION", name="fk_master_run_receipt_run",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint(
            "operation IN ('pause','resume','cancel','verify')",
            name="ck_master_run_receipt_operation",
        ),
        CheckConstraint("expected_revision > 0", name="ck_master_run_receipt_expected"),
        CheckConstraint(
            "result_revision = expected_revision + 1", name="ck_master_run_receipt_result",
        ),
        Index("ix_master_run_receipt_run", "project_id", "master_run_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    master_run_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    result_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_data: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "MASTER_RUN_CONTROL_OPERATIONS",
    "MASTER_RUN_DESIRED_STATES",
    "MASTER_RUN_STATUSES",
    "DirectorMasterRun",
    "DirectorMasterRunControlReceipt",
    "DirectorMasterRunPlan",
]
