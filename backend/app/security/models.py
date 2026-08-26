"""ORM records for encrypted BYOK credentials and rotation audit metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class EncryptedProviderCredential(Base):
    """An immutable account-credential revision.

    Account updates create a new row and retain the previous row through
    ``supersedes_id``.  The key-rotation maintenance command is the sole
    intentional in-place mutation of ``ciphertext``/``key_version``; those
    fields describe encryption state, not account revision identity.
    """

    __tablename__ = "encrypted_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "revision_no",
            name="uq_encrypted_provider_credential_revision",
        ),
        # The composite identity gives PostgreSQL a valid target for the
        # composite predecessor FK below, which prevents cross-provider or
        # cross-workspace predecessor links at the database boundary.
        UniqueConstraint(
            "id",
            "workspace_id",
            "provider",
            name="uq_encrypted_provider_credential_identity",
        ),
        ForeignKeyConstraint(
            ["supersedes_id", "workspace_id", "provider"],
            [
                "encrypted_provider_credentials.id",
                "encrypted_provider_credentials.workspace_id",
                "encrypted_provider_credentials.provider",
            ],
            name="fk_encrypted_provider_credential_supersedes_identity",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_no > 0",
            name="ck_encrypted_provider_credential_revision_positive",
        ),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_encrypted_provider_credential_not_self_superseding",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    revision_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(nullable=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
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
