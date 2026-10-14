"""Availability never promotes an unverified model or revision to Create-ready."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import clear_settings_cache
from app.providers.availability_models import (
    ProviderAvailabilityEvidence,
)
from app.providers.availability_projection import (
    ModelAvailabilityObservation,
    record_model_availability,
)
from app.providers.connection_service import ProviderConnectionService
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from app.shared.security import hash_password
from cryptography.fernet import Fernet
from sqlalchemy import func, select
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


@pytest.mark.asyncio
async def test_exact_revision_positive_and_transient_projection(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{Fernet.generate_key().decode('ascii')}")
    clear_settings_cache()
    owner = User(
        email=f"availability-{uuid4().hex}@example.com",
        display_name="Availability Owner",
        password_hash=hash_password("password123"),
    )
    session.add(owner)
    await session.flush()
    workspace = Workspace(owner_user_id=owner.id, name="Availability")
    session.add(workspace)
    await session.flush()
    connections = ProviderConnectionService(session)
    connection = await connections.create_connection(
        workspace_id=workspace.id,
        actor=owner,
        display_name="MiniMax",
        api_key="fake-test-key",
        enabled=True,
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
    )
    first_revision = await connections.current_connection_revision(connection=connection)
    exact = {
        "workspace_id": workspace.id,
        "connection_id": connection.id,
        "connection_revision_id": first_revision.id,
        "credential_revision_id": first_revision.credential_revision_id,
        "remote_model_id": "MiniMax-H3",
        "verifier_kind": "model_list",
    }

    with pytest.raises(ValueError, match="returned model ids"):
        await record_model_availability(
            session, ModelAvailabilityObservation(**exact, status="visible")
        )
    with pytest.raises(ValueError, match="contradicts"):
        await record_model_availability(
            session,
            ModelAvailabilityObservation(
                **exact, status="visible", listed_model_ids=("different-model",)
            ),
        )
    assert await session.scalar(select(func.count()).select_from(ProviderAvailabilityEvidence)) == 0

    visible = await record_model_availability(
        session,
        ModelAvailabilityObservation(
            **exact, status="visible", listed_model_ids=("MiniMax-H3", "image-01")
        ),
    )
    positive_id = visible.positive_evidence_id
    assert visible.effective_status == "visible"
    assert positive_id is not None

    transient = await record_model_availability(
        session, ModelAvailabilityObservation(**exact, status="temporary_error")
    )
    assert transient.effective_status == "visible"
    assert transient.positive_evidence_id == positive_id
    assert transient.latest_evidence_id != positive_id

    denied = await record_model_availability(
        session, ModelAvailabilityObservation(**exact, status="auth_failed")
    )
    assert denied.effective_status == "auth_failed"
    after_denial = await record_model_availability(
        session, ModelAvailabilityObservation(**exact, status="temporary_error")
    )
    assert after_denial.effective_status == "auth_failed"

    second_revision = await connections.create_connection_revision(connection=connection)
    stale = await record_model_availability(
        session,
        ModelAvailabilityObservation(
            **exact,
            status="visible",
            listed_model_ids=("MiniMax-H3",),
        ),
    )
    assert stale is None
    fresh = await record_model_availability(
        session,
        ModelAvailabilityObservation(
            **{
                **exact,
                "connection_revision_id": second_revision.id,
                "credential_revision_id": second_revision.credential_revision_id,
            },
            status="temporary_error",
        ),
    )
    assert fresh.effective_status == "not_checked"
    assert fresh.positive_evidence_id is None
    assert await session.scalar(select(func.count()).select_from(ProviderAvailabilityEvidence)) == 6
