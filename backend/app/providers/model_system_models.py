"""Expanded model truth and connection evidence for the one-way cutover.

These rows coexist with the old catalog only during Migration A. They never
manufacture account visibility from a legacy binding boolean.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class ModelCapabilityRevision(Base):
    __tablename__ = "model_capability_revisions"
    __table_args__ = (
        UniqueConstraint(
            "provider_type",
            "protocol_profile",
            "canonical_model_id",
            "model_revision",
            name="uq_model_capability_identity",
        ),
        UniqueConstraint("legacy_catalog_entry_id", name="uq_model_capability_legacy_catalog"),
        CheckConstraint(
            "implementation_status IN ('not_implemented','manifest_mapped','contract_tested')",
            name="ck_model_capability_implementation_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    legacy_catalog_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_model_catalog_entries.id", ondelete="RESTRICT"), nullable=True
    )
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(120), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    documented_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    implementation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manifest_mapped"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelPublicationState(Base):
    __tablename__ = "model_publication_states"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('active','legacy','deprecated','retired','unknown')",
            name="ck_model_publication_lifecycle",
        ),
    )

    model_capability_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_capability_revisions.id", ondelete="RESTRICT"), primary_key=True
    )
    lifecycle: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelPublicationEvent(Base):
    __tablename__ = "model_publication_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model_capability_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_capability_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    from_lifecycle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_lifecycle: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConnectionDiscoveredModel(Base):
    __tablename__ = "connection_discovered_models"
    __table_args__ = (
        UniqueConstraint(
            "connection_revision_id",
            "credential_revision_id",
            "remote_model_id",
            name="uq_connection_discovered_model_identity",
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
    protocol_contract_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConnectionModelCapabilityRevision(Base):
    __tablename__ = "connection_model_capability_revisions"
    __table_args__ = (
        UniqueConstraint(
            "connection_discovered_model_id",
            "capability_revision",
            name="uq_connection_model_capability_revision",
        ),
        CheckConstraint(
            "implementation_status IN ('not_implemented','manifest_mapped','contract_tested')",
            name="ck_connection_model_implementation_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_discovered_model_id: Mapped[UUID] = mapped_column(
        ForeignKey("connection_discovered_models.id", ondelete="RESTRICT"), nullable=False
    )
    capability_revision: Mapped[str] = mapped_column(String(80), nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operations_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_contracts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parameter_constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    protocol_contract_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    implementation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_implemented"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
    effective_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_checked"
    )
    positive_evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"), nullable=True
    )
    latest_evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
