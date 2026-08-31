"""Workspace provider connections, capability evidence, and model bindings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider_type",
            "protocol_profile",
            name="uq_provider_connection_profile",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(240), nullable=False)
    protocol_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    credential_revision: Mapped[int] = mapped_column(nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    verification_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unverified"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class ProviderConnectionRevision(Base):
    """Immutable execution configuration for one ProviderConnection."""

    __tablename__ = "provider_connection_revisions"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "revision_no",
            name="uq_provider_connection_revision_no",
        ),
        CheckConstraint(
            "revision_no > 0",
            name="ck_provider_connection_revision_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "provider_connections.id",
            name="fk_provider_connection_revision_connection",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="1"
    )
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(240), nullable=False)
    credential_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "encrypted_provider_credentials.id",
            name="fk_provider_connection_revision_credential",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderCapabilityEvidence(Base):
    __tablename__ = "provider_capability_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(60), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(40), nullable=False)
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reference_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    remote_query_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Binding-scoped probe evidence: exactly which model binding (and catalog
    # revision) this capability proof belongs to. Never advances other bindings.
    model_binding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "provider_model_bindings.id",
            name="fk_provider_capability_evidence_model_binding",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    capability_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_revision: Mapped[int | None] = mapped_column(nullable=True)
    budget_authorized: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0")
    )
    provider_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    cost_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_reported")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ProviderModelBinding(Base):
    __tablename__ = "provider_model_bindings"
    __table_args__ = (
        # One binding per (connection, media, catalog revision, purpose): the
        # same model may have multiple revisions coexist as distinct bindings.
        UniqueConstraint(
            "connection_id",
            "media_type",
            "catalog_entry_id",
            "purpose",
            name="uq_provider_model_binding_revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="CASCADE"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    documented: Mapped[bool] = mapped_column(nullable=False, default=True)
    contract_tested: Mapped[bool] = mapped_column(nullable=False, default=True)
    account_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    quality_gated: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Immutable catalog snapshot: which catalog revision this binding uses and
    # what value is actually written to the wire request ``model`` field.
    catalog_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "provider_model_catalog_entries.id",
            name="fk_provider_model_bindings_catalog_entry",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    capability_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_resource_kind: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="model"
    )
    remote_resource_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    invoke_model_value: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Workspace owner supplied, explicitly acknowledged estimate.  Catalog
    # prices remain immutable global documentation; this snapshot captures the
    # user's actual account/contract price for a concrete binding revision.
    pricing_snapshot_json: Mapped[dict[str, object]] = mapped_column(
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


class ProjectProviderBinding(Base):
    __tablename__ = "project_provider_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "purpose", name="uq_project_provider_binding"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    model_binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_model_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    # A+B scope: only explicit_binding is enabled (auto is not open yet).
    selection_strategy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="explicit_binding"
    )
    fallback_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    updated_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderQualityEvidence(Base):
    """Immutable proof used to advance one model binding to quality_gated."""

    __tablename__ = "provider_quality_evidence"
    __table_args__ = (
        UniqueConstraint(
            "model_binding_id",
            "node_run_id",
            name="uq_provider_quality_evidence_run",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_model_bindings.id", ondelete="CASCADE"), nullable=False
    )
    node_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("node_runs.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    approved_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ArtifactReferenceToken(Base):
    """One-artifact public delivery grant; only the token hash is persisted."""

    __tablename__ = "artifact_reference_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_artifact_reference_token_hash"),
        CheckConstraint(
            "(created_by_run_id IS NOT NULL) <> (created_by_user_id IS NOT NULL)",
            name="ck_artifact_reference_token_creator",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("node_runs.id", ondelete="CASCADE"), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "ix_provider_connection_revisions_connection_id",
    ProviderConnectionRevision.__table__.c.connection_id,
)
Index(
    "ix_provider_model_bindings_catalog_entry_id",
    ProviderModelBinding.__table__.c.catalog_entry_id,
)
Index(
    "ix_provider_capability_evidence_model_binding_id",
    ProviderCapabilityEvidence.__table__.c.model_binding_id,
)
