"""Recheck the frozen target's current Create permission without replacing it."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.availability_models import (
    ProviderAvailabilityEvidence,
    ProviderModelAvailability,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_publication import (
    effective_publication_lifecycle,
    lock_catalog_publication,
)
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.shared.errors import ValidationAppError


async def require_frozen_create_admission(
    session: AsyncSession,
    identity: ExecutionIdentitySnapshot,
) -> None:
    """This is a Create gate only. Historical resume must not call it."""
    await lock_catalog_publication(session, shared=True)
    # The compiler may already have loaded these rows. Reload and hold their
    # current permission through the durable submission marker commit.
    connection = await session.scalar(
        select(ProviderConnection)
        .where(ProviderConnection.id == identity.connection_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    binding = await session.scalar(
        select(ProviderModelBinding)
        .where(ProviderModelBinding.id == identity.provider_model_binding_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    entry = await session.scalar(
        select(ModelCatalogEntry)
        .where(ModelCatalogEntry.id == identity.catalog_entry_id)
        .execution_options(populate_existing=True)
    )
    if connection is None or binding is None or entry is None:
        raise ValidationAppError(
            "已选模型身份不完整", details={"code": "MODEL_BINDING_UNAVAILABLE"}
        )
    lifecycle = effective_publication_lifecycle(
        entry.provider_type, entry.protocol_profile, entry.model_id, entry.lifecycle
    )
    if not connection.enabled or not binding.enabled or lifecycle != "active":
        raise ValidationAppError(
            "当前模型不允许新建请求", details={"code": "MODEL_CREATE_NOT_ALLOWED"}
        )
    if entry.catalog_source == "protocol_contract":
        raise ValidationAppError(
            "动态模型只有协议合同，缺少精确型号能力确认，暂不允许新建请求",
            details={"code": "DYNAMIC_MODEL_CAPABILITY_UNVERIFIED"},
        )
    current_revision = await session.scalar(
        select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == connection.id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    if current_revision is None or (
        current_revision.id != identity.connection_revision_id
        or current_revision.credential_revision_id != identity.credential_revision_id
        or connection.credential_id != identity.credential_revision_id
        or current_revision.provider_type != connection.provider_type
        or current_revision.protocol_profile != connection.protocol_profile
        or current_revision.base_url != connection.base_url
    ):
        raise ValidationAppError(
            "连接或凭据已更新，请重新预览", details={"code": "MODEL_CREATE_REVISION_CHANGED"}
        )
    if (
        binding.connection_id != connection.id
        or binding.workspace_id != connection.workspace_id
        or binding.catalog_entry_id != entry.id
        or binding.invoke_model_value != identity.invoke_model_value
        or entry.contract_manifest_hash != identity.manifest_hash
        or not binding.documented
        or not binding.contract_tested
        or not binding.account_verified
    ):
        raise ValidationAppError(
            "已选模型资格已变化，请重新预览", details={"code": "MODEL_CREATE_NOT_ALLOWED"}
        )
    visible = await session.scalar(
        select(ProviderModelAvailability).where(
            ProviderModelAvailability.workspace_id == connection.workspace_id,
            ProviderModelAvailability.connection_id == identity.connection_id,
            ProviderModelAvailability.connection_revision_id == identity.connection_revision_id,
            ProviderModelAvailability.credential_revision_id == identity.credential_revision_id,
            ProviderModelAvailability.remote_model_id == binding.model_id,
            ProviderModelAvailability.effective_status == "visible",
        )
    )
    evidence = (
        await session.get(ProviderAvailabilityEvidence, visible.positive_evidence_id)
        if (visible is not None and visible.positive_evidence_id is not None)
        else None
    )
    if evidence is None or (
        evidence.workspace_id != connection.workspace_id
        or evidence.connection_id != identity.connection_id
        or evidence.connection_revision_id != identity.connection_revision_id
        or evidence.credential_revision_id != identity.credential_revision_id
        or evidence.remote_model_id != binding.model_id
        or evidence.status != "visible"
        or binding.model_id not in (evidence.listed_model_ids_json or [])
    ):
        raise ValidationAppError(
            "当前冻结连接缺少该模型的正向可见性证据",
            details={"code": "MODEL_VISIBILITY_NOT_VERIFIED"},
        )
