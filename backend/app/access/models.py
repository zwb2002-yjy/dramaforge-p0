"""Access domain ORM models (organizations, users, membership). Fields mirror `04`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
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
from app.shared.enums import ExperienceMode, MemberRole, ProjectStage

# PG native enums (create_type=False — Alembic owns types); SQLite uses string values.
_member_role = Enum(
    MemberRole,
    name="member_role",
    native_enum=True,
    create_constraint=False,
    values_callable=lambda e: [m.value for m in e],
    validate_strings=True,
)
_project_stage = Enum(
    ProjectStage,
    name="project_stage",
    native_enum=True,
    create_constraint=False,
    values_callable=lambda e: [m.value for m in e],
    validate_strings=True,
)
_experience_mode = Enum(
    ExperienceMode,
    name="experience_mode",
    native_enum=True,
    create_constraint=False,
    values_callable=lambda e: [m.value for m in e],
    validate_strings=True,
)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
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


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (PrimaryKeyConstraint("organization_id", "user_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MemberRole | str] = mapped_column(
        _member_role.with_variant(String(32), "sqlite"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def role_enum(self) -> MemberRole:
        return self.role if isinstance(self.role, MemberRole) else MemberRole(self.role)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_projects_org_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    stage: Mapped[ProjectStage | str] = mapped_column(
        _project_stage.with_variant(String(32), "sqlite"),
        nullable=False,
        default=ProjectStage.DRAFT,
    )
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    style_bible: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    budget_limit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    budget_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    provider_dispatch_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (PrimaryKeyConstraint("project_id", "user_id"),)

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MemberRole | str] = mapped_column(
        _member_role.with_variant(String(32), "sqlite"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserProjectPreference(Base):
    __tablename__ = "user_project_preferences"
    __table_args__ = (PrimaryKeyConstraint("user_id", "project_id"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    experience_mode: Mapped[ExperienceMode | str] = mapped_column(
        _experience_mode.with_variant(String(32), "sqlite"),
        nullable=False,
        default=ExperienceMode.WORKBENCH,
    )
    last_guided_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
