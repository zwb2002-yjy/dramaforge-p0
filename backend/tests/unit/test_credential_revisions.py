"""Security and identity regressions for immutable BYOK credential revisions."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import Settings
from app.providers.models import ProviderConnection
from app.providers.workspace_credentials import runtime_connection_settings
from app.security.byok_keyring import parse_keyring
from app.security.credentials import (
    read_credential,
    read_credential_by_id,
    rotate_credentials,
    store_credential,
)
from app.security.models import KeyRotationAudit
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


def _key() -> str:
    return Fernet.generate_key().decode("ascii")


async def _workspace(session: AsyncSession) -> Workspace:
    user = User(
        email=f"credential-revision-{uuid4().hex}@example.com",
        display_name="Credential Revision Owner",
        password_hash="hash",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(
        owner_user_id=user.id,
        name=f"Credential Revision Workspace {uuid4().hex[:8]}",
    )
    session.add(workspace)
    await session.flush()
    return workspace


@pytest.mark.asyncio
async def test_account_updates_insert_revisions_and_strict_reads_are_workspace_scoped(
    session: AsyncSession,
) -> None:
    workspace = await _workspace(session)
    other_workspace = await _workspace(session)
    keyring = parse_keyring(
        primary_version="v1",
        encoded=f"v1:{_key()}",
        legacy_key="",
    )

    first = await store_credential(
        session,
        workspace_id=workspace.id,
        provider="agnes",
        plaintext="account-a-secret",
        keyring=keyring,
    )
    first_ciphertext = first.ciphertext
    second = await store_credential(
        session,
        workspace_id=workspace.id,
        provider="agnes",
        plaintext="account-b-secret",
        keyring=keyring,
    )

    assert second.id != first.id
    assert first.revision_no == 1
    assert second.revision_no == 2
    assert second.supersedes_id == first.id
    assert first.ciphertext == first_ciphertext
    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=first.id,
        keyring=keyring,
    ) == "account-a-secret"
    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=second.id,
        keyring=keyring,
    ) == "account-b-secret"
    assert await read_credential_by_id(
        session,
        workspace_id=other_workspace.id,
        credential_id=first.id,
        keyring=keyring,
    ) is None
    # The provider-key helper remains a legacy compatibility lookup and points
    # to the latest account revision only; concrete connections use the ID API.
    assert await read_credential(
        session,
        workspace_id=workspace.id,
        provider="agnes",
        keyring=keyring,
    ) == "account-b-secret"
    assert "account-a-secret" not in first.ciphertext
    assert "account-b-secret" not in second.ciphertext


@pytest.mark.asyncio
async def test_runtime_connection_settings_uses_named_revision_not_latest_provider_default(
    session: AsyncSession,
) -> None:
    workspace = await _workspace(session)
    key_material = _key()
    keyring = parse_keyring(
        primary_version="v1",
        encoded=f"v1:{key_material}",
        legacy_key="",
    )
    first = await store_credential(
        session,
        workspace_id=workspace.id,
        provider="agnes",
        plaintext="connection-rev-one-secret",
        keyring=keyring,
    )
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://connection.example.test",
        protocol_profile="agnes_cn_v1",
        credential_id=first.id,
        credential_revision=first.revision_no,
        enabled=True,
        verification_status="verified",
        created_by=workspace.owner_user_id,
        updated_by=workspace.owner_user_id,
    )
    session.add(connection)
    await session.flush()
    await store_credential(
        session,
        workspace_id=workspace.id,
        provider="agnes",
        plaintext="connection-rev-two-secret",
        keyring=keyring,
    )

    settings = Settings(
        byok_primary_key_version="v1",
        byok_keyring=f"v1:{key_material}",
        byok_fernet_key=key_material,
    )
    resolved = await runtime_connection_settings(
        session,
        connection=connection,
        settings=settings,
    )

    assert resolved.agnes_api_key == "connection-rev-one-secret"
    assert resolved.agnes_api_key != "connection-rev-two-secret"
    assert resolved.agnes_base_url == "https://connection.example.test"


@pytest.mark.asyncio
async def test_key_rotation_changes_encryption_state_without_creating_account_revision(
    session: AsyncSession,
) -> None:
    workspace = await _workspace(session)
    old_key = _key()
    new_key = _key()
    old = parse_keyring(primary_version="v1", encoded=f"v1:{old_key}", legacy_key="")
    both = parse_keyring(
        primary_version="v2",
        encoded=f"v1:{old_key},v2:{new_key}",
        legacy_key="",
    )
    first = await store_credential(
        session,
        workspace_id=workspace.id,
        provider="text",
        plaintext="text-revision-one",
        keyring=old,
    )
    second = await store_credential(
        session,
        workspace_id=workspace.id,
        provider="text",
        plaintext="text-revision-two",
        keyring=old,
    )
    revisions = {
        first.id: (first.revision_no, first.supersedes_id),
        second.id: (second.revision_no, second.supersedes_id),
    }

    result = await rotate_credentials(
        session,
        keyring=both,
        actor_label="identity-a-test",
    )

    assert result.scanned == 2
    assert result.reencrypted == 2
    assert result.already_primary == 0
    assert (first.revision_no, first.supersedes_id) == revisions[first.id]
    assert (second.revision_no, second.supersedes_id) == revisions[second.id]
    assert first.key_version == second.key_version == "v2"
    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=first.id,
        keyring=both,
    ) == "text-revision-one"
    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=second.id,
        keyring=both,
    ) == "text-revision-two"
    audit = await session.scalar(select(KeyRotationAudit))
    assert audit is not None
    assert audit.reencrypted_count == 2


@pytest.mark.asyncio
async def test_missing_named_connection_credential_fails_closed_without_environment_fallback(
    session: AsyncSession,
) -> None:
    workspace = await _workspace(session)
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://connection.example.test",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=workspace.owner_user_id,
        updated_by=workspace.owner_user_id,
    )
    session.add(connection)
    await session.flush()

    from app.providers.workspace_credentials import WorkspaceCredentialConfigurationError

    key_material = _key()
    settings = Settings(
        byok_primary_key_version="v1",
        byok_keyring=f"v1:{key_material}",
        byok_fernet_key=key_material,
        agnes_api_key="environment-secret-must-not-be-used",
        agnes_enabled=True,
    )
    with pytest.raises(WorkspaceCredentialConfigurationError):
        await runtime_connection_settings(session, connection=connection, settings=settings)
    assert "environment-secret-must-not-be-used" not in str(connection.__dict__)

