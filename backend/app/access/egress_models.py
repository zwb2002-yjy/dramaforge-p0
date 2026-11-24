"""Project egress policy, policy head and trusted destination declarations (M03).

These tables hold *declarations and permissions*, never a second egress task or a
copy of provider configuration. A destination revision is an immutable statement
about a real, already-registered binding; a policy revision is an immutable
permission set for one project. The head row is the only mutable pointer.
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

EGRESS_PURPOSES = (
    "director_text",
    "research_text",
    "vision_input",
    "image_generation",
    "video_generation",
    "voice_generation",
    "reference_delivery",
    "result_download",
    "remote_recovery",
    "external_storage",
)
PROCESSING_LOCATIONS = ("local", "external", "unknown")
EGRESS_MODES = ("current", "local_only", "allowlisted")


class ProviderDestinationRevision(Base):
    """Immutable declaration of where one registered binding sends data."""

    __tablename__ = "provider_destination_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "binding_ref", "revision", name="uq_destination_binding_revision",
        ),
        UniqueConstraint(
            "workspace_id", "binding_ref", "origin_expected_revision",
            name="uq_destination_binding_origin",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_destination_workspace_scope"),
        ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT",
            name="fk_destination_workspace",
        ),
        CheckConstraint("revision > 0", name="ck_destination_revision"),
        CheckConstraint("origin_expected_revision >= 0", name="ck_destination_origin_revision"),
        CheckConstraint(
            "processing_location IN ('local','external','unknown')",
            name="ck_destination_location",
        ),
        Index("ix_destination_binding", "workspace_id", "binding_ref", "revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    binding_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_expected_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    upstream_origin: Mapped[str] = mapped_column(Text, nullable=False)
    processing_location: Mapped[str] = mapped_column(String(16), nullable=False)
    purposes: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    declaration_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    route_manifest: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    location_evidence: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ProjectEgressPolicyRevision(Base):
    """Immutable permission set for one project at one revision."""

    __tablename__ = "project_egress_policy_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_egress_policy_revision"),
        UniqueConstraint(
            "project_id", "origin_expected_revision", name="uq_egress_policy_origin",
        ),
        UniqueConstraint("id", "project_id", name="uq_egress_policy_scope"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT", name="fk_egress_policy_project",
        ),
        CheckConstraint("revision > 0", name="ck_egress_policy_revision"),
        CheckConstraint("origin_expected_revision >= 0", name="ck_egress_policy_origin"),
        CheckConstraint(
            "mode IN ('current','local_only','allowlisted')", name="ck_egress_policy_mode",
        ),
        Index("ix_egress_policy_project", "project_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_data: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    policy_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ProjectEgressPolicyHead(Base):
    """Current pointer for one project; the only mutable row in this table set."""

    __tablename__ = "project_egress_policy_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT", name="fk_egress_head_project",
        ),
        ForeignKeyConstraint(
            ["current_revision_id", "project_id"],
            [
                "project_egress_policy_revisions.id",
                "project_egress_policy_revisions.project_id",
            ],
            name="fk_egress_head_revision", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED", use_alter=True,
        ),
        CheckConstraint("revision > 0", name="ck_egress_head_revision"),
    )

    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "EGRESS_MODES",
    "EGRESS_PURPOSES",
    "PROCESSING_LOCATIONS",
    "ProjectEgressPolicyHead",
    "ProjectEgressPolicyRevision",
    "ProviderDestinationRevision",
]
