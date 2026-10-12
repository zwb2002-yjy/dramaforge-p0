"""Permission revoked during compilation is reloaded before the submission marker."""

from uuid import uuid4

import pytest
from app.providers.create_admission import require_frozen_create_admission
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.shared.errors import ValidationAppError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import (
    _FAKE_MANIFEST,
    FAKE_PROFILE,
    FAKE_PROVIDER,
    _byok,
    _project,
    _seed_binding,
)
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


@pytest.mark.parametrize("target", [ProviderConnection, ProviderModelBinding])
async def test_second_session_disable_overrides_compilers_cached_permission(
    pg_session, monkeypatch, target
):
    _byok(monkeypatch)
    user, project_id, workspace_id = await _project(pg_session)
    model_id = f"permission-{uuid4().hex[:12]}"
    binding, connection = await _seed_binding(
        pg_session,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user.id,
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        model_id=model_id,
        media_kind="video",
        purpose="video",
        manifest=_FAKE_MANIFEST,
        invoke_model_value=model_id,
    )
    await pg_session.commit()
    revision = await pg_session.scalar(
        select(ProviderConnectionRevision).where(
            ProviderConnectionRevision.connection_id == connection.id
        )
    )
    identity = ExecutionIdentitySnapshot(
        resolved_model=f"{FAKE_PROVIDER}/{model_id}",
        resolution_source="frozen",
        provider_model_binding_id=binding.id,
        catalog_entry_id=binding.catalog_entry_id,
        model_revision="v1",
        manifest_hash=binding.capability_manifest_hash,
        invoke_model_value=model_id,
        connection_id=connection.id,
        connection_revision_id=revision.id,
        credential_revision_id=revision.credential_revision_id,
        capability="video.generate",
        mode_id="first_frame",
        request_fingerprint="a" * 64,
    )
    assert binding.enabled and connection.enabled
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    row_id = connection.id if target is ProviderConnection else binding.id
    async with factory() as other:
        await other.execute(update(target).where(target.id == row_id).values(enabled=False))
        await other.commit()
    assert binding.enabled and connection.enabled
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(pg_session, identity)
    assert exc.value.details["code"] == "MODEL_CREATE_NOT_ALLOWED"
    assert (connection if target is ProviderConnection else binding).enabled is False
