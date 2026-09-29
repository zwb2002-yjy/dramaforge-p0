"""Availability never promotes an unverified model or revision to Create-ready."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import clear_settings_cache
from app.providers.availability_projection import (
    ModelAvailabilityObservation,
    record_model_availability,
)
from app.providers.binding_cutover import build_binding_cutover_report
from app.providers.connection_service import ProviderConnectionService
from app.providers.model_system_models import (
    ModelCapabilityRevision,
    ModelPublicationState,
    ProviderAvailabilityEvidence,
)
from app.providers.models import ProviderModelBinding
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
    assert await session.scalar(select(func.count()).select_from(ProviderAvailabilityEvidence)) == 5

    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id="MiniMax-H3",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        invoke_model_value="MiniMax-H3",
        created_by=owner.id,
        updated_by=owner.id,
    )
    session.add(binding)
    await session.flush()
    unresolved = await build_binding_cutover_report(session, workspace_id=workspace.id)
    assert unresolved.enabled_unresolved_count == 1
    assert unresolved.rows[0].availability == "not_checked"
    assert "binding_target_unresolved" in unresolved.rows[0].blocking_reasons

    model = ModelCapabilityRevision(
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        canonical_model_id="MiniMax-H3",
        model_revision="v1",
        media_kind="video",
        manifest_json={},
        manifest_hash="a" * 64,
        source_snapshot_id="minimax-test-snapshot",
        implementation_status="contract_tested",
    )
    session.add(model)
    await session.flush()
    session.add(ModelPublicationState(model_capability_revision_id=model.id, lifecycle="active"))
    binding.binding_target_kind = "global_model"
    binding.model_capability_revision_id = model.id
    binding.canonical_model_id = model.canonical_model_id
    await session.flush()
    target_ready = await build_binding_cutover_report(session, workspace_id=workspace.id)
    assert target_ready.enabled_unresolved_count == 0
    assert target_ready.enabled_blocked_count == 1
    assert target_ready.rows[0].blocking_reasons == ("availability_not_visible",)

    await record_model_availability(
        session,
        ModelAvailabilityObservation(
            **{
                **exact,
                "connection_revision_id": second_revision.id,
                "credential_revision_id": second_revision.credential_revision_id,
            },
            status="visible",
            listed_model_ids=("MiniMax-H3",),
        ),
    )
    ready = await build_binding_cutover_report(session, workspace_id=workspace.id)
    assert ready.enabled_blocked_count == 0
    assert ready.rows[0].binding_id == binding.id
    assert ready.rows[0].availability == "visible"

    connection.provider_type = "agnes"
    mismatched = await build_binding_cutover_report(session, workspace_id=workspace.id)
    assert mismatched.enabled_unresolved_count == 1
    assert "global_target_unresolved" in mismatched.rows[0].blocking_reasons
