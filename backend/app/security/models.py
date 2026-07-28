"""ORM records for encrypted BYOK credentials and rotation audit metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class EncryptedProviderCredential(Base):
    __tablename__ = "encrypted_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", name="uq_encrypted_provider_credential"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KeyRotationAudit(Base):
    __tablename__ = "key_rotation_audits"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_label: Mapped[str] = mapped_column(String(120), nullable=False)
    primary_key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reencrypted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
