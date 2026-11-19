"""ProductionModelProfile ORM (spec §58–§60).

``bindings`` is a JSON column keyed by ModelSlot value (``planning.script`` →
``{"model_id": "...", "native_options": {}, "enabled": true}``). P0 keeps the
profile as configuration data (not a hot relational query), so JSONB-style
storage matches the repo's existing JSON usage and the spec §59 decision.
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
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT


class ProductionModelProfile(Base):
    __tablename__ = "production_model_profiles"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "name", "project_id", name="uq_model_profile_workspace_name"
        ),
        UniqueConstraint("project_id", name="uq_model_profile_project"),
        CheckConstraint(
            "media_config_version IN (1, 2)",
            name="ck_model_profile_media_config_version",
        ),
        CheckConstraint(
            "project_id IS NOT NULL OR (image_model_binding_id IS NULL "
            "AND video_model_binding_id IS NULL AND voice_model_binding_id IS NULL "
            "AND voice_options = '{}')",
            name="ck_model_profile_workspace_media_empty",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "image_model_binding_id"],
            ["provider_model_bindings.workspace_id", "provider_model_bindings.id"],
            ondelete="RESTRICT", name="fk_model_profile_image_binding",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "video_model_binding_id"],
            ["provider_model_bindings.workspace_id", "provider_model_bindings.id"],
            ondelete="RESTRICT", name="fk_model_profile_video_binding",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "voice_model_binding_id"],
            ["provider_model_bindings.workspace_id", "provider_model_bindings.id"],
            ondelete="RESTRICT", name="fk_model_profile_voice_binding",
        ),
        Index(
            "ix_model_profile_image_model_binding_id",
            "image_model_binding_id",
            postgresql_where=text("image_model_binding_id IS NOT NULL"),
        ),
        Index(
            "ix_model_profile_video_model_binding_id",
            "video_model_binding_id",
            postgresql_where=text("video_model_binding_id IS NOT NULL"),
        ),
        Index(
            "ix_model_profile_voice_model_binding_id",
            "voice_model_binding_id",
            postgresql_where=text("voice_model_binding_id IS NOT NULL"),
        ),
        # PostgreSQL treats NULL project_id values as distinct, so the plain
        # constraint cannot dedupe workspace-level profiles. This partial index
        # closes that hole for rows without a project.
        Index(
            "uq_model_profile_workspace_name_null_project",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
            sqlite_where=text("project_id IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = workspace-level profile; non-NULL = this project's profile.
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    media_config_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=2, server_default="2"
    )
    image_model_binding_id: Mapped[UUID | None] = mapped_column(nullable=True)
    video_model_binding_id: Mapped[UUID | None] = mapped_column(nullable=True)
    voice_model_binding_id: Mapped[UUID | None] = mapped_column(nullable=True)
    voice_options: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict, server_default="{}"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bindings: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "ix_production_model_profiles_workspace_id",
    ProductionModelProfile.__table__.c.workspace_id,
)
Index(
    "uq_model_profile_workspace_default",
    ProductionModelProfile.__table__.c.workspace_id,
    unique=True,
    postgresql_where=text("is_default AND project_id IS NULL"),
)
