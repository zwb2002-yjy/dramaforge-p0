"""Persist and rotate encrypted workspace-scoped provider credentials."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.byok_keyring import ByokKeyring
from app.security.models import EncryptedProviderCredential, KeyRotationAudit


@dataclass(frozen=True)
class RotationResult:
    scanned: int
    reencrypted: int
    already_primary: int


async def store_credential(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    plaintext: str,
    keyring: ByokKeyring,
) -> EncryptedProviderCredential:
    encrypted = keyring.encrypt(plaintext)
    # Account credential changes are revisions, never updates.  Lock the
    # current head when the backend supports row locks; the revision unique
    # constraint remains the final guard for concurrent writers.
    latest = await session.scalar(
        select(EncryptedProviderCredential)
        .where(
            EncryptedProviderCredential.workspace_id == workspace_id,
            EncryptedProviderCredential.provider == provider,
        )
        .order_by(EncryptedProviderCredential.revision_no.desc())
        .limit(1)
        .with_for_update()
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


async def has_credential(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
) -> bool:
    """Return whether an workspace has a stored credential without decrypting it."""
    return (
        await session.scalar(
            select(EncryptedProviderCredential.id).where(
                EncryptedProviderCredential.workspace_id == workspace_id,
                EncryptedProviderCredential.provider == provider,
            )
        )
    ) is not None


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
