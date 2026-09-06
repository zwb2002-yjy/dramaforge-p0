"""Model catalog entry (global, read-only, versioned model capability rows)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class ModelCatalogEntry(Base):
    """One immutable capability manifest revision for one concrete model.

    Global data (no ``workspace_id``), written only by migrations. Runtime access
    is read-only; the application role has SELECT granted and write revoked.
    A contract change adds a new row (new ``model_revision``); the old row is
    marked ``lifecycle='deprecated'``. Bindings point at a specific revision.
    """

    __tablename__ = "provider_model_catalog_entries"
    __table_args__ = (
        UniqueConstraint(
            "provider_type",
            "protocol_profile",
            "model_id",
            "model_revision",
            name="uq_provider_catalog_entry_revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    catalog_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="official_static"
    )
    capability_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    option_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    pricing_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    documented_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def manifest(self) -> dict[str, Any]:
        return self.capability_manifest_json
