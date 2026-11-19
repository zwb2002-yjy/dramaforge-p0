"""Durable BusinessFlow instances, steps and attempts (I6a-01).

A BusinessFlow is the Director's durable projection of one registered business
definition inside an accepted plan. It owns step/attempt coordination only: the
actual work stays with the existing controlled domain tools, Turn/Invocation
evidence and Production NodeRuns. These models never become a second runtime,
queue or media state machine.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT

FLOW_INSTANCE_STATUSES = (
    "pending",
    "running",
    "waiting",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
)
FLOW_STEP_STATUSES = (
    "pending",
    "ready",
    "running",
    "waiting_user",
    "waiting_execution",
    "blocked",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
    "superseded",
)
FLOW_ATTEMPT_STATUSES = (
    "pending",
    "running",
    "waiting_user",
    "waiting_execution",
    "unknown_submission",
    "succeeded",
    "failed",
    "cancelled",
)
FLOW_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
FLOW_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"pending", "running", "waiting_user", "waiting_execution", "unknown_submission"}
)
FLOW_ACTION_KINDS = ("read", "proposal", "apply", "production", "repair", "review")

_INSTANCE_STATUS_SQL = ",".join(f"'{value}'" for value in FLOW_INSTANCE_STATUSES)
_STEP_STATUS_SQL = ",".join(f"'{value}'" for value in FLOW_STEP_STATUSES)
_ATTEMPT_STATUS_SQL = ",".join(f"'{value}'" for value in FLOW_ATTEMPT_STATUSES)
_ACTION_KIND_SQL = ",".join(f"'{value}'" for value in FLOW_ACTION_KINDS)


class DirectorBusinessFlowInstance(Base):
    """One frozen flow of an accepted plan; identity columns never change."""

    __tablename__ = "director_business_flow_instances"
    __table_args__ = (
        UniqueConstraint(
            "supervisor_run_id", "plan_id", "flow_key", name="uq_flow_instance_run_plan_flow",
        ),
        UniqueConstraint(
            "id", "supervisor_run_id", "plan_id", "plan_revision", "project_id",
            name="uq_flow_instance_plan_identity",
        ),
        ForeignKeyConstraint(
            ["supervisor_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            ondelete="NO ACTION", name="fk_flow_instance_run",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["plan_id", "plan_revision", "supervisor_run_id", "project_id"],
            [
                "director_master_run_plans.id",
                "director_master_run_plans.revision",
                "director_master_run_plans.master_run_id",
                "director_master_run_plans.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_instance_plan",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_turn_id", "supervisor_run_id", "plan_revision", "project_id"],
            [
                "director_turns.id",
                "director_turns.master_run_id",
                "director_turns.plan_revision",
                "director_turns.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_instance_turn",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("revision > 0", name="ck_flow_instance_revision"),
        CheckConstraint("plan_revision > 0", name="ck_flow_instance_plan_revision"),
        CheckConstraint(
            f"status IN ({_INSTANCE_STATUS_SQL})", name="ck_flow_instance_status",
        ),
        CheckConstraint(
            "scope_type IN ('project','scene','shot')", name="ck_flow_instance_scope",
        ),
        CheckConstraint(
            "(status IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)",
            name="ck_flow_instance_finished",
        ),
        CheckConstraint(
            "(status IN ('succeeded','failed','cancelled')) = (terminal_reason IS NOT NULL)",
            name="ck_flow_instance_terminal_reason",
        ),
        CheckConstraint(
            "status IN ('succeeded','failed','cancelled') OR wait_reason IS NOT NULL "
            "OR status = 'pending'",
            name="ck_flow_instance_wait_reason",
        ),
        Index(
            "ix_flow_instances_run_status",
            "project_id", "supervisor_run_id", "status",
        ),
        Index(
            "ix_flow_instances_active",
            "updated_at", "id",
            postgresql_where=text(
                "status NOT IN ('succeeded','failed','cancelled')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    supervisor_run_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    flow_key: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_key: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    input_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    created_by_turn_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    wait_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DirectorBusinessFlowStep(Base):
    """One registered step of a flow instance; dependencies stay frozen."""

    __tablename__ = "director_business_flow_steps"
    __table_args__ = (
        UniqueConstraint("instance_id", "step_key", name="uq_flow_step_instance_key"),
        UniqueConstraint(
            "id", "instance_id", "supervisor_run_id", "plan_id", "plan_revision",
            "project_id", "scope_type", "scope_entity_id",
            name="uq_flow_step_attempt_identity",
        ),
        ForeignKeyConstraint(
            [
                "instance_id", "supervisor_run_id", "plan_id", "plan_revision", "project_id",
            ],
            [
                "director_business_flow_instances.id",
                "director_business_flow_instances.supervisor_run_id",
                "director_business_flow_instances.plan_id",
                "director_business_flow_instances.plan_revision",
                "director_business_flow_instances.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_step_instance",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("revision > 0", name="ck_flow_step_revision"),
        CheckConstraint(f"status IN ({_STEP_STATUS_SQL})", name="ck_flow_step_status"),
        CheckConstraint(
            "scope_type IN ('project','scene','shot')", name="ck_flow_step_scope",
        ),
        Index("ix_flow_steps_instance_status", "instance_id", "status", "step_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    instance_id: Mapped[UUID] = mapped_column(nullable=False)
    supervisor_run_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    input_refs: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    completion_spec: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    dependencies: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    result_refs: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    wait_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DirectorBusinessFlowStepAttempt(Base):
    """One attempt of one step; a single attempt carries at most one receipt."""

    __tablename__ = "director_business_flow_step_attempts"
    __table_args__ = (
        UniqueConstraint("step_id", "attempt_no", name="uq_flow_attempt_step_no"),
        UniqueConstraint("project_id", "command_key", name="uq_flow_attempt_command"),
        UniqueConstraint(
            "id", "supervisor_run_id", "plan_revision", "project_id",
            "scope_type", "scope_entity_id",
            name="uq_flow_attempt_turn_identity",
        ),
        ForeignKeyConstraint(
            [
                "step_id", "instance_id", "supervisor_run_id", "plan_id", "plan_revision",
                "project_id", "scope_type", "scope_entity_id",
            ],
            [
                "director_business_flow_steps.id",
                "director_business_flow_steps.instance_id",
                "director_business_flow_steps.supervisor_run_id",
                "director_business_flow_steps.plan_id",
                "director_business_flow_steps.plan_revision",
                "director_business_flow_steps.project_id",
                "director_business_flow_steps.scope_type",
                "director_business_flow_steps.scope_entity_id",
            ],
            ondelete="NO ACTION", name="fk_flow_attempt_step",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["node_run_id", "project_id"], ["node_runs.id", "node_runs.project_id"],
            ondelete="NO ACTION", name="fk_flow_attempt_node_run",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["authorization_ref", "project_id"],
            ["production_command_authorizations.id",
             "production_command_authorizations.project_id"],
            ondelete="NO ACTION", name="fk_flow_attempt_authorization",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("revision > 0", name="ck_flow_attempt_revision"),
        CheckConstraint("attempt_no > 0", name="ck_flow_attempt_no"),
        CheckConstraint("control_epoch >= 0", name="ck_flow_attempt_epoch"),
        CheckConstraint(
            f"status IN ({_ATTEMPT_STATUS_SQL})", name="ck_flow_attempt_status",
        ),
        CheckConstraint(
            f"action_kind IN ({_ACTION_KIND_SQL})", name="ck_flow_attempt_action_kind",
        ),
        CheckConstraint(
            "scope_type IN ('project','scene','shot')", name="ck_flow_attempt_scope",
        ),
        CheckConstraint(
            "status <> 'unknown_submission' OR unresolved_external",
            name="ck_flow_attempt_unknown_unresolved",
        ),
        CheckConstraint(
            "action_kind <> 'production' OR status NOT IN ('succeeded') OR node_run_id IS NOT NULL",
            name="ck_flow_attempt_production_receipt",
        ),
        Index("ix_flow_attempts_project_status", "project_id", "status", "updated_at", "id"),
        Index(
            "uq_flow_attempt_active_step",
            "step_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending','running','waiting_user','waiting_execution',"
                "'unknown_submission') OR unresolved_external"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    instance_id: Mapped[UUID] = mapped_column(nullable=False)
    supervisor_run_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    control_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    payload_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    action_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    action_key: Mapped[str] = mapped_column(String(120), nullable=False)
    command_key: Mapped[str] = mapped_column(String(200), nullable=False)
    authorization_ref: Mapped[UUID | None] = mapped_column(nullable=True)
    node_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    receipt_ref: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    result_refs: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    unresolved_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = [
    "DirectorBusinessFlowInstance",
    "DirectorBusinessFlowStep",
    "DirectorBusinessFlowStepAttempt",
    "FLOW_ACTION_KINDS",
    "FLOW_ACTIVE_ATTEMPT_STATUSES",
    "FLOW_ATTEMPT_STATUSES",
    "FLOW_INSTANCE_STATUSES",
    "FLOW_STEP_STATUSES",
    "FLOW_TERMINAL_STATUSES",
]
