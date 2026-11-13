"""Persist and rotate encrypted workspace-scoped provider credentials."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.byok_keyring import ByokKeyring
from app.security.models import EncryptedProviderCredential, KeyRotationAudit
from app.shared.errors import NotFoundError


@dataclass(frozen=True)
class RotationResult:
    scanned: int
    reencrypted: int
    already_primary: int


async def lock_workspace_credentials(session: AsyncSession, *, workspace_id: UUID) -> None:
    """Serialize revision writers on their stable parent, including first writes.

    Connection writers take this lock before a connection lock. SQLite fixtures
    cannot prove this concurrency contract; PostgreSQL is the runtime authority.
    """
    if session.get_bind().dialect.name == "postgresql":
        with session.no_autoflush:
            parent = await session.scalar(
                text("SELECT id FROM workspaces WHERE id = :id FOR UPDATE"),
                {"id": workspace_id},
            )
        if parent is None:
            raise NotFoundError("workspace not found")


async def store_credential(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    plaintext: str,
    keyring: ByokKeyring,
) -> EncryptedProviderCredential:
    await lock_workspace_credentials(session, workspace_id=workspace_id)
    encrypted = keyring.encrypt(plaintext)
    # Read the head after the stable parent lock: waiting on the previous head
    # alone could allocate its successor twice.
    latest = await session.scalar(
        select(EncryptedProviderCredential)
        .where(
            EncryptedProviderCredential.workspace_id == workspace_id,
            EncryptedProviderCredential.provider == provider,
        )
        .order_by(EncryptedProviderCredential.revision_no.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    record = EncryptedProviderCredential(
        workspace_id=workspace_id,
        provider=provider,
        revision_no=(latest.revision_no + 1) if latest is not None else 1,
        supersedes_id=latest.id if latest is not None else None,
        ciphertext=encrypted.ciphertext,
        key_version=encrypted.key_version,
    )
    session.add(record)
    await session.flush()
    return record


async def read_credential(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    keyring: ByokKeyring,
) -> str | None:
    """Legacy provider-key lookup; Professional connections use ID lookup."""
    record = await session.scalar(
        select(EncryptedProviderCredential)
        .where(
            EncryptedProviderCredential.workspace_id == workspace_id,
            EncryptedProviderCredential.provider == provider,
        )
        .order_by(EncryptedProviderCredential.revision_no.desc())
        .limit(1)
    )
    if record is None:
        return None
    return keyring.decrypt(ciphertext=record.ciphertext, key_version=record.key_version)


async def read_credential_by_id(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    credential_id: UUID,
    keyring: ByokKeyring,
) -> str | None:
    """Decrypt exactly the credential revision named by a connection.

    The workspace predicate is deliberately repeated alongside the primary-key
    lookup.  A UUID alone is not sufficient authorization for a credential
    read, and a missing or cross-workspace row is treated as unavailable by
    the concrete runtime callers.
    """
    record = await session.scalar(
        select(EncryptedProviderCredential).where(
            EncryptedProviderCredential.id == credential_id,
            EncryptedProviderCredential.workspace_id == workspace_id,
        )
    )
    if record is None:
        return None
    return keyring.decrypt(ciphertext=record.ciphertext, key_version=record.key_version)



async def rotate_credentials(
    session: AsyncSession,
    *,
    keyring: ByokKeyring,
    actor_label: str,
) -> RotationResult:
    """Re-encrypt credentials and write metadata-only audit evidence."""
    records = list(
        (
            await session.scalars(
                select(EncryptedProviderCredential).order_by(EncryptedProviderCredential.id)
            )
        ).all()
    )
    changed = 0
    unchanged = 0
    for record in records:
        if record.key_version == keyring.primary_version:
            unchanged += 1
            continue
        plaintext = keyring.decrypt(
            ciphertext=record.ciphertext,
            key_version=record.key_version,
        )
        encrypted = keyring.encrypt(plaintext)
        record.ciphertext = encrypted.ciphertext
        record.key_version = encrypted.key_version
        changed += 1
    session.add(
        KeyRotationAudit(
            actor_label=actor_label,
            primary_key_version=keyring.primary_version,
            scanned_count=len(records),
            reencrypted_count=changed,
        )
    )
    await session.flush()
    return RotationResult(
        scanned=len(records),
        reencrypted=changed,
        already_primary=unchanged,
    )
