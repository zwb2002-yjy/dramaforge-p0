"""Shared unit-test fixture: a workspace that can actually resolve workbench models.

Unit tests that dispatch a real ``NodeRun`` need the catalog entry, provider
connection, binding and profile rows the resolver reads. Keeping one helper here
avoids three drifting copies (the ORM constructor signatures are detailed).
"""

from __future__ import annotations

from datetime import date

from app.access.models import Project, User
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.security.models import EncryptedProviderCredential
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _catalog_entry(
    session: AsyncSession,
    *,
    model_id: str,
    media_kind: str,
    display_name: str,
) -> ModelCatalogEntry:
    """Return the seeded catalog entry, creating it only when absent.

    The migration chain already seeds the official agnes catalog on PostgreSQL,
    so an unconditional insert would violate the catalog's unique key.
    """
    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == model_id)
    existing = (
        await session.execute(
            select(ModelCatalogEntry).where(
                ModelCatalogEntry.provider_type == "agnes",
                ModelCatalogEntry.protocol_profile == "agnes_cn_v1",
                ModelCatalogEntry.model_id == model_id,
                ModelCatalogEntry.model_revision == "v1",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id=model_id,
        model_revision="v1",
        display_name=display_name,
        media_kind=media_kind,
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    return entry


async def seed_model_infra(session: AsyncSession, *, project: Project, user: User) -> None:
    """Seed catalog + connection + bindings + profile for video/keyframe."""
    entry = await _catalog_entry(
        session, model_id="agnes-video-v2.0", media_kind="video", display_name="Agnes Video"
    )
    # The connection names an encrypted credential revision; PostgreSQL enforces
    # that reference, so the credential row must exist before the connection.
    # Resolution tests never decrypt this placeholder, and no real key material
    # belongs in a fixture.
    credential = EncryptedProviderCredential(
        workspace_id=project.workspace_id,
        provider="agnes",
        revision_no=1,
        ciphertext="fixture-not-a-real-ciphertext",
        key_version="fixture",
    )
    session.add(credential)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=project.workspace_id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=credential.id,
        credential_revision=credential.revision_no,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    revision = ProviderConnectionRevision(
        connection_id=connection.id,
        revision_no=1,
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        base_url="https://api.agnes-ai.cn",
        credential_revision_id=connection.credential_id,
    )
    session.add(revision)
    await session.flush()
    session.add(
        ProviderModelBinding(
            workspace_id=project.workspace_id,
            connection_id=connection.id,
            media_type="video",
            model_id="agnes-video-v2.0",
            purpose="video",
            enabled=True,
            documented=True,
            contract_tested=True,
            account_verified=True,
            quality_gated=True,
            catalog_entry_id=entry.id,
            capability_manifest_hash=entry.contract_manifest_hash,
            remote_resource_kind="model",
            remote_resource_id="agnes-video-v2.0",
            invoke_model_value="agnes-video-v2.0",
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.flush()
    image_entry = await _catalog_entry(
        session,
        model_id="agnes-image-2.1-flash",
        media_kind="image",
        display_name="Agnes Image",
    )
    session.add(
        ProviderModelBinding(
            workspace_id=project.workspace_id,
            connection_id=connection.id,
            media_type="image",
            model_id="agnes-image-2.1-flash",
            purpose="keyframe",
            enabled=True,
            documented=True,
            contract_tested=True,
            account_verified=True,
            quality_gated=True,
            catalog_entry_id=image_entry.id,
            capability_manifest_hash=image_entry.contract_manifest_hash,
            remote_resource_kind="model",
            remote_resource_id="agnes-image-2.1-flash",
            invoke_model_value="agnes-image-2.1-flash",
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.flush()
    bindings = {
        "video.shot": {
            "slot": "video.shot",
            "model_id": "agnes-video-v2.0",
            "native_options": {},
            "enabled": True,
        },
        "visual.keyframe": {
            "slot": "visual.keyframe",
            "model_id": "agnes-image-2.1-flash",
            "native_options": {},
            "enabled": True,
        },
    }
    session.add(
        ProductionModelProfile(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name="default",
            version=1,
            is_default=True,
            bindings=bindings,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.flush()


__all__ = ["seed_model_infra"]
