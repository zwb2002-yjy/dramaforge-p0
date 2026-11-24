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
from app.shared.db import set_rls_context
from app.shared.errors import ValidationAppError
from sqlalchemy import select, text, update
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


@pytest.mark.parametrize(
    "target", [ProviderConnection, ProviderModelBinding, None, "catalog_retirement"]
)
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
    if target == "catalog_retirement":
        import asyncio
        import json
        from pathlib import Path

        from app.providers.catalog_loader import LoadedCatalogManifest
        from app.providers.catalog_models import ModelCatalogEntry
        from app.providers.catalog_sync import sync_model_catalog

        entry = await pg_session.get(ModelCatalogEntry, binding.catalog_entry_id)
        retired = LoadedCatalogManifest(
            identity=(
                entry.provider_type,
                entry.protocol_profile,
                entry.model_id,
                entry.model_revision,
            ),
            manifest_hash=entry.contract_manifest_hash,
            publication_lifecycle="retired",
            source_path=Path(__file__),
            _canonical_json=json.dumps(entry.capability_manifest_json),
        )
        await require_frozen_create_admission(pg_session, identity)
        factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
        started = asyncio.Event()
        owner = {}

        async def publish_retirement():
            async with factory() as maintenance:
                owner["pid"] = await maintenance.scalar(text("SELECT pg_backend_pid()"))
                started.set()
                result = await sync_model_catalog(maintenance, manifests=(retired,), apply=True)
                await maintenance.commit()
                return result

        publisher = asyncio.create_task(publish_retirement())
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            waiting = False
            for _ in range(40):
                waiting = bool(
                    await pg_session.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                            "AND locktype='advisory' AND NOT granted)"
                        ),
                        owner,
                    )
                )
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting and not publisher.done()
            # The durable submission-marker transaction releases the shared
            # lock. No Provider submission is made by this test.
            await pg_session.commit()
            result = await asyncio.wait_for(publisher, timeout=5)
            assert result.lifecycle_updated == (retired.identity,)
            with pytest.raises(ValidationAppError) as blocked:
                await require_frozen_create_admission(pg_session, identity)
            assert blocked.value.details["code"] == "MODEL_CREATE_NOT_ALLOWED"
        finally:
            await pg_session.rollback()
            if not publisher.done():
                publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
        return
    if target is None:
        await set_rls_context(
            pg_session, user_id=user.id, workspace_id=workspace_id, project_id=project_id
        )
        await pg_session.execute(text("SET LOCAL ROLE dramaforge_app"))
        assert not await pg_session.scalar(
            text(
                "SELECT has_table_privilege(current_user, "
                "'provider_model_catalog_entries', 'UPDATE')"
            )
        )
        await require_frozen_create_admission(pg_session, identity)
        return
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
