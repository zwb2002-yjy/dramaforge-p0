"""Shared fixtures for provider model/binding resolution tests.

The seed helper builds one connection with two concrete model bindings whose
catalog revisions carry distinct manifest hashes, so tests can assert that a
requested model identity is never substituted by sibling/seed order.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_two_models(
    session: AsyncSession,
) -> tuple[ProviderConnection, ProviderModelBinding, ProviderModelBinding]:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"runtime-resolution-{suffix}@example.com",
        display_name="Runtime resolution",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Runtime {suffix}")
    session.add(workspace)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="same-provider",
        display_name="Same provider",
        base_url="https://provider.example.com",
        protocol_profile="same-profile",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()

    bindings: list[ProviderModelBinding] = []
    for model_id, wire_model, marker in (
        ("model-a", "wire-model-a", "a"),
        ("model-b", "wire-model-b", "b"),
    ):
        manifest_hash = marker * 64
        entry = ModelCatalogEntry(
            provider_type="same-provider",
            protocol_profile="same-profile",
            model_id=model_id,
            model_revision="v1",
            display_name=model_id,
            media_kind="video",
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json={"model_id": model_id},
            option_schema_json={},
            documented_at=date(2026, 8, 26),
            contract_manifest_hash=manifest_hash,
        )
        session.add(entry)
        await session.flush()
        binding = ProviderModelBinding(
            workspace_id=workspace.id,
            connection_id=connection.id,
            media_type="video",
            model_id=model_id,
            purpose="video",
            enabled=True,
            documented=True,
            contract_tested=True,
            account_verified=True,
            quality_gated=True,
            catalog_entry_id=entry.id,
            capability_manifest_hash=manifest_hash,
            remote_resource_kind="model",
            remote_resource_id=model_id,
            invoke_model_value=wire_model,
            created_by=user.id,
            updated_by=user.id,
        )
        bindings.append(binding)
        session.add(binding)
        await session.flush()
    return connection, bindings[0], bindings[1]
