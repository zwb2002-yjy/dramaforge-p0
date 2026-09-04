"""Keyring tests prove the retained-old-key rotation contract."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.security.byok_keyring import (
    KeyringConfigurationError,
    UnknownKeyVersionError,
    parse_keyring,
)
from app.security.credentials import read_credential, rotate_credentials, store_credential
from app.security.models import EncryptedProviderCredential, KeyRotationAudit
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _key() -> str:
    return Fernet.generate_key().decode("ascii")


def test_keyring_decrypts_retained_version_and_rejects_revoked_version() -> None:
    old_key = _key()
    new_key = _key()
    old = parse_keyring(primary_version="v1", encoded=f"v1:{old_key}", legacy_key="")
    encrypted = old.encrypt("provider-token")
    rotated = parse_keyring(
        primary_version="v2",
        encoded=f"v1:{old_key},v2:{new_key}",
        legacy_key="",
    )

    assert rotated.decrypt(
        ciphertext=encrypted.ciphertext,
        key_version=encrypted.key_version,
    ) == "provider-token"
    with pytest.raises(UnknownKeyVersionError):
        parse_keyring(primary_version="v2", encoded=f"v2:{new_key}", legacy_key="").decrypt(
            ciphertext=encrypted.ciphertext,
            key_version=encrypted.key_version,
        )


def test_keyring_requires_primary_in_retained_set() -> None:
    with pytest.raises(KeyringConfigurationError):
        parse_keyring(primary_version="v2", encoded=f"v1:{_key()}", legacy_key="")


def test_credential_rotation_reencrypts_and_records_metadata_only_audit() -> None:
    async def run() -> None:
        load_all_models()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        old_key = _key()
        new_key = _key()
        old = parse_keyring(primary_version="v1", encoded=f"v1:{old_key}", legacy_key="")
        both = parse_keyring(
            primary_version="v2",
            encoded=f"v1:{old_key},v2:{new_key}",
            legacy_key="",
        )
        owner_id = uuid4()
        workspace_id = uuid4()
        async with factory() as session:
            session.add(
                User(
                    id=owner_id,
                    email="byok-owner@example.com",
                    display_name="Owner",
                    password_hash="hash",
                )
            )
            session.add(
                Workspace(
                    id=workspace_id,
                    owner_user_id=owner_id,
                    name="BYOK workspace",
                )
            )
            await session.flush()
            record = await store_credential(
                session,
                workspace_id=workspace_id,
                provider="text",
                plaintext="provider-token",
                keyring=old,
            )
            first_ciphertext = record.ciphertext
            result = await rotate_credentials(session, keyring=both, actor_label="rotation-drill")
            await session.commit()
            assert result.scanned == 1
            assert result.reencrypted == 1
            assert record.key_version == "v2"
            assert record.ciphertext != first_ciphertext
        async with factory() as session:
            assert await read_credential(
                session,
                workspace_id=workspace_id,
                provider="text",
                keyring=both,
            ) == "provider-token"
            audit = await session.scalar(select(KeyRotationAudit))
            assert audit is not None
            assert audit.actor_label == "rotation-drill"
            assert audit.primary_key_version == "v2"
            assert audit.reencrypted_count == 1
            stored = await session.scalar(select(EncryptedProviderCredential))
            assert stored is not None
            assert "provider-token" not in stored.ciphertext
        await engine.dispose()

    asyncio.run(run())
