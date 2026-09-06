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
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base


class ProductionModelProfile(Base):
    __tablename__ = "production_model_profiles"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "name", "project_id", name="uq_model_profile_workspace_name"
        ),
        UniqueConstraint("project_id", name="uq_model_profile_project"),
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
