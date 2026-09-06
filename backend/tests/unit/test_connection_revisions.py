"""MS5-IDENTITY-B connection revision and workspace isolation tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import clear_settings_cache
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from app.security.credentials import read_credential_by_id, store_credential
from app.security.models import EncryptedProviderCredential
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.model_registry import load_all_models
from app.shared.security import hash_password
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


def _configure_byok(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()


async def _owner_workspace(session: AsyncSession, label: str) -> tuple[User, Workspace]:
    user = User(
        email=f"connection-revision-{label}-{uuid4().hex}@example.com",
        display_name="Connection Revision Owner",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Revision {label}")
    session.add(workspace)
    await session.flush()
    return user, workspace


@pytest.mark.asyncio
async def test_connection_revisions_track_execution_changes_but_not_display_changes(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _key()
    _configure_byok(monkeypatch, key)
    user, workspace = await _owner_workspace(session, "lifecycle")
    service = ProviderConnectionService(session)

    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Agnes",
        api_key="account-revision-one",
        enabled=True,
    )
    first = await service.current_connection_revision(connection=connection)
    assert first.revision_no == 1
    assert first.provider_type == connection.provider_type
    assert first.protocol_profile == connection.protocol_profile
    assert first.base_url == "https://api.agnes-ai.cn"
    assert first.credential_revision_id == connection.credential_id

    await service.update_connection(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        display_name="Renamed Agnes",
        enabled=False,
    )
    still_first = await service.current_connection_revision(connection=connection)
    assert still_first.id == first.id

    await service.update_connection(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        display_name=None,
        enabled=None,
        base_url="https://new.agnes.example",
    )
    second = await service.current_connection_revision(connection=connection)
    assert second.id != first.id
    assert second.revision_no == 2
    assert second.base_url == "https://new.agnes.example"
    assert first.base_url == "https://api.agnes-ai.cn"
    assert first.credential_revision_id == second.credential_revision_id

    await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="account-revision-two",
    )
    third = await service.current_connection_revision(connection=connection)
    assert third.revision_no == 3
    assert third.credential_revision_id != second.credential_revision_id
    assert third.base_url == second.base_url
    assert second.credential_revision_id == first.credential_revision_id

    revisions = list(
        (
            await session.scalars(
                select(ProviderConnectionRevision)
                .where(ProviderConnectionRevision.connection_id == connection.id)
                .order_by(ProviderConnectionRevision.revision_no)
            )
        ).all()
    )
    assert [item.revision_no for item in revisions] == [1, 2, 3]
    assert [item.id for item in revisions] == [first.id, second.id, third.id]

    first_credential = await session.get(
        EncryptedProviderCredential, first.credential_revision_id
    )
    third_credential = await session.get(
        EncryptedProviderCredential, third.credential_revision_id
    )
    assert first_credential is not None
    assert third_credential is not None
    from app.providers.workspace_credentials import configured_byok_keyring

    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=first_credential.id,
        keyring=configured_byok_keyring(),
    ) == "account-revision-one"
    assert await read_credential_by_id(
        session,
        workspace_id=workspace.id,
        credential_id=third_credential.id,
        keyring=configured_byok_keyring(),
    ) == "account-revision-two"


@pytest.mark.asyncio
async def test_connection_revision_rejects_foreign_workspace_credential(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _key()
    _configure_byok(monkeypatch, key)
    owner_a, workspace_a = await _owner_workspace(session, "a")
    _owner_b, workspace_b = await _owner_workspace(session, "b")
    from app.providers.workspace_credentials import configured_byok_keyring

    foreign_credential = await store_credential(
        session,
        workspace_id=workspace_b.id,
        provider="agnes",
        plaintext="foreign-workspace-secret",
        keyring=configured_byok_keyring(),
    )
    connection = ProviderConnection(
        workspace_id=workspace_a.id,
        provider_type="agnes",
        display_name="Foreign",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=foreign_credential.id,
        credential_revision=foreign_credential.revision_no,
        enabled=True,
        verification_status="unverified",
        created_by=owner_a.id,
        updated_by=owner_a.id,
    )
    session.add(connection)
    await session.flush()

    with pytest.raises(ValidationAppError) as caught:
        await ProviderConnectionService(session).create_connection_revision(
            connection=connection
        )
    assert getattr(caught.value, "details", {}).get("code") == (
        "PROVIDER_CONNECTION_CREDENTIAL_INVALID"
    )
    assert (
        await session.scalar(
            select(ProviderConnectionRevision).where(
                ProviderConnectionRevision.connection_id == connection.id
            )
        )
        is None
    )
