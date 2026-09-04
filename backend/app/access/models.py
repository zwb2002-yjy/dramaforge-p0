"""Access domain ORM models for private user-owned workspaces."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base
from app.shared.db_types import CURRENCY_CODE, JSON_DOCUMENT
from app.shared.enums import ProjectStage

# PG native enums (create_type=False — Alembic owns types); SQLite uses string values.
_project_stage = Enum(
    ProjectStage,
    name="project_stage",
    native_enum=True,
    create_constraint=False,
    values_callable=lambda e: [m.value for m in e],
    validate_strings=True,
)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_workspaces_owner_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InstanceBootstrapState(Base):
    """Non-sensitive singleton tracking the first self-hosted Owner.

    This table intentionally has no user-scoped RLS: unauthenticated bootstrap
    must be able to answer only whether an Owner already exists. User records
    remain protected by their existing FORCE RLS policy.
    """

    __tablename__ = "instance_bootstrap_state"
    __table_args__ = (
        CheckConstraint(
            "singleton_id = 1", name="ck_instance_bootstrap_state_singleton"
        ),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_projects_workspace_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    stage: Mapped[ProjectStage | str] = mapped_column(
        _project_stage.with_variant(String(32), "sqlite"),
        nullable=False,
        default=ProjectStage.DRAFT,
    )
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    style_bible: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    budget_limit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    budget_currency: Mapped[str] = mapped_column(
        CURRENCY_CODE, nullable=False, default="USD"
    )
    provider_dispatch_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class UserProjectPreference(Base):
    __tablename__ = "user_project_preferences"
    __table_args__ = (PrimaryKeyConstraint("user_id", "project_id"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workspace_state: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProjectCreativeProfile(Base):
    """One canonical Creative Profile per Project (V1 Template/Free start)."""

    __tablename__ = "project_creative_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    start_type: Mapped[str] = mapped_column(String(16), nullable=False, default="FREE")
    created_from_template_key: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    template_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_contract_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    director_autonomy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ASSIST"
    )
    selected_genre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    selected_style_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    selected_skill_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    selected_shot_language: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    asset_slot_requirements: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    strategy_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "idx_projects_workspace_stage",
    Project.__table__.c.workspace_id,
    Project.__table__.c.stage,
)
