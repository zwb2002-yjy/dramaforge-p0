"""Persist and rotate encrypted organization-scoped provider credentials."""

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
    organization_id: UUID,
    provider: str,
    plaintext: str,
    keyring: ByokKeyring,
) -> EncryptedProviderCredential:
    encrypted = keyring.encrypt(plaintext)
    record = await session.scalar(
        select(EncryptedProviderCredential).where(
            EncryptedProviderCredential.organization_id == organization_id,
            EncryptedProviderCredential.provider == provider,
        )
    )
    if record is None:
        record = EncryptedProviderCredential(
            organization_id=organization_id,
            provider=provider,
            ciphertext=encrypted.ciphertext,
            key_version=encrypted.key_version,
        )
        session.add(record)
    else:
        record.ciphertext = encrypted.ciphertext
        record.key_version = encrypted.key_version
    await session.flush()
    return record


async def read_credential(
    session: AsyncSession,
    *,
    organization_id: UUID,
    provider: str,
    keyring: ByokKeyring,
) -> str | None:
    record = await session.scalar(
        select(EncryptedProviderCredential).where(
            EncryptedProviderCredential.organization_id == organization_id,
            EncryptedProviderCredential.provider == provider,
        )
    )
    if record is None:
        return None
    return keyring.decrypt(ciphertext=record.ciphertext, key_version=record.key_version)


async def has_credential(
    session: AsyncSession,
    *,
    organization_id: UUID,
    provider: str,
) -> bool:
    """Return whether an organization has a stored credential without decrypting it."""
    return (
        await session.scalar(
            select(EncryptedProviderCredential.id).where(
                EncryptedProviderCredential.organization_id == organization_id,
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
