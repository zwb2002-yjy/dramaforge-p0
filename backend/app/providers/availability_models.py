"""Exact connection/credential/model availability evidence and its projection."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class ProviderAvailabilityEvidence(Base):
    """Append-only result of checking one exact remote model on one revision."""

    __tablename__ = "provider_availability_evidence"
    __table_args__ = (
        CheckConstraint(
            "status IN ('visible','not_visible','auth_failed','forbidden',"
            "'region_unavailable','temporary_error','not_supported')",
            name="ck_provider_availability_evidence_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False
    )
    connection_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connection_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    credential_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"), nullable=False
    )
    remote_model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    verifier_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    listed_model_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderModelAvailability(Base):
    """Current projection; temporary errors never erase prior positive proof."""

    __tablename__ = "provider_model_availability"
    __table_args__ = (
        UniqueConstraint(
            "connection_revision_id",
            "credential_revision_id",
            "remote_model_id",
            name="uq_provider_model_availability_identity",
        ),
        CheckConstraint(
            "effective_status IN ('visible','not_checked','not_visible','auth_failed',"
            "'forbidden','region_unavailable','not_supported')",
            name="ck_provider_model_availability_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False
    )
    connection_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connection_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    credential_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"), nullable=False
    )
    remote_model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    effective_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_checked")
    positive_evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"), nullable=True
    )
    latest_evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
