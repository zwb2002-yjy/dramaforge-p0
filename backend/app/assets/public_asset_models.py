"""Public asset publications, their fixed items and project fixed links (I5-01).

A publication freezes one adopted AssetVersion's safe display facts and its real media
items; it never mirrors the private source project. Project links pin one publication
and one local label; later publications never move an existing link.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class PublicAssetPublication(Base):
    __tablename__ = "public_asset_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_workspace",
        ),
        ForeignKeyConstraint(
            ["source_project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_project",
        ),
        ForeignKeyConstraint(
            ["source_asset_version_id", "source_project_id"],
            ["asset_versions.id", "asset_versions.project_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_version",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint(
            "source_asset_version_id", name="uq_public_asset_publication_version",
        ),
        UniqueConstraint("id", "owner_user_id", name="uq_public_asset_publication_owner"),
        UniqueConstraint(
            "id", "source_project_id", "workspace_id", "owner_user_id",
            name="uq_public_asset_publication_scope",
        ),
        UniqueConstraint(
            "id", "source_asset_version_id", "owner_user_id",
            name="uq_public_asset_publication_version_owner",
        ),
        CheckConstraint(
            "status IN ('available','restricted','withdrawn')",
            name="ck_public_asset_publication_status",
        ),
        CheckConstraint("revision > 0", name="ck_public_asset_publication_revision"),
        CheckConstraint(
            "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)",
            name="ck_public_asset_publication_withdrawn",
        ),
        Index(
            "ix_public_asset_publication_owner", "owner_user_id", "status", "kind", "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    source_project_id: Mapped[UUID] = mapped_column(nullable=False)
    source_asset_id: Mapped[UUID] = mapped_column(nullable=False)
    source_asset_version_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_name: Mapped[str] = mapped_column(String(160), nullable=False)
    safe_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    safe_metadata: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    publication_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="available", server_default="available",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PublicAssetPublicationItem(Base):
    __tablename__ = "public_asset_publication_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["publication_id", "source_asset_version_id", "owner_user_id"],
            [
                "public_asset_publications.id",
                "public_asset_publications.source_asset_version_id",
                "public_asset_publications.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_public_item_publication",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "source_reference_id",
                "source_asset_version_id",
                "artifact_id",
                "source_project_id",
            ],
            [
                "asset_version_references.id",
                "asset_version_references.asset_version_id",
                "asset_version_references.artifact_id",
                "asset_version_references.project_id",
            ],
            ondelete="RESTRICT", name="fk_public_item_reference",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint(
            "publication_id", "source_reference_id", name="uq_public_item_reference",
        ),
        UniqueConstraint(
            "id", "publication_id", "artifact_id", "owner_user_id",
            name="uq_public_item_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    publication_id: Mapped[UUID] = mapped_column(nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    source_project_id: Mapped[UUID] = mapped_column(nullable=False)
    source_asset_version_id: Mapped[UUID] = mapped_column(nullable=False)
    source_reference_id: Mapped[UUID] = mapped_column(nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ProjectPublicAssetLink(Base):
    __tablename__ = "project_public_asset_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_public_link_project",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_public_link_workspace",
        ),
        ForeignKeyConstraint(
            ["publication_id", "source_asset_version_id", "owner_user_id"],
            [
                "public_asset_publications.id",
                "public_asset_publications.source_asset_version_id",
                "public_asset_publications.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_public_link_publication",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint("project_id", "publication_id", name="uq_public_link_publication"),
        UniqueConstraint("project_id", "request_key", name="uq_public_link_request"),
        UniqueConstraint(
            "id", "project_id", name="uq_public_link_project_scope",
        ),
        UniqueConstraint(
            "id", "project_id", "publication_id", name="uq_public_link_base",
        ),
        UniqueConstraint(
            "id", "project_id", "publication_id", "source_asset_version_id",
            name="uq_public_link_version_scope",
        ),
        UniqueConstraint(
            "id", "project_id", "publication_id", "owner_user_id",
            name="uq_public_link_owner_scope",
        ),
        CheckConstraint("version > 0", name="ck_public_link_version"),
        Index("ix_public_link_project", "project_id", "detached_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    publication_id: Mapped[UUID] = mapped_column(nullable=False)
    source_asset_version_id: Mapped[UUID] = mapped_column(nullable=False)
    local_label: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default="",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "ProjectPublicAssetLink",
    "PublicAssetPublication",
    "PublicAssetPublicationItem",
]
