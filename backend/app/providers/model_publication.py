"""Maintenance publication of new immutable Global model capability revisions.

The current runtime does not read these rows. Publication records the reviewed
capability body while lifecycle starts unknown until separately evidenced.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_loader import hash_manifest
from app.providers.manifest import ModelCapabilityManifest
from app.providers.model_system_models import (
    ModelCapabilityRevision,
    ModelPublicationEvent,
    ModelPublicationState,
)

_IMPLEMENTATION_STATUS = {
    "discovered": "not_implemented",
    "documented": "manifest_mapped",
    "contract_tested": "contract_tested",
}
ModelLifecycle = Literal["active", "legacy", "deprecated", "retired", "unknown"]


async def publish_global_model_revision(
    session: AsyncSession,
    *,
    manifest: dict[str, Any],
    source_snapshot_id: str,
    documented_at: date,
) -> ModelCapabilityRevision:
    """Insert a new revision; neither source evidence nor lifecycle is inferred."""
    snapshot_id = source_snapshot_id.strip()
    if not snapshot_id or len(snapshot_id) > 120:
        raise ValueError("a bounded source snapshot id is required")
    validated = ModelCapabilityManifest.model_validate(manifest)
    if validated.documented_at != documented_at:
        raise ValueError("documented_at must match the reviewed manifest")
    body = dict(manifest)
    body.pop("lifecycle", None)
    body.pop("catalog_source", None)
    row = ModelCapabilityRevision(
        provider_type=validated.provider_type,
        protocol_profile=validated.protocol_profile,
        canonical_model_id=validated.model_id,
        model_revision=validated.model_revision,
        media_kind=validated.media_kind,
        manifest_json=body,
        manifest_hash=hash_manifest(body),
        source_snapshot_id=snapshot_id,
        documented_at=documented_at,
        implementation_status=_IMPLEMENTATION_STATUS[validated.implementation_status],
    )
    session.add(row)
    await session.flush()
    session.add(ModelPublicationState(model_capability_revision_id=row.id, lifecycle="unknown"))
    session.add(
        ModelPublicationEvent(
            model_capability_revision_id=row.id,
            from_lifecycle=None,
            to_lifecycle="unknown",
            reason="new_capability_revision_requires_lifecycle_review",
        )
    )
    await session.flush()
    return row


async def set_model_publication_lifecycle(
    session: AsyncSession,
    *,
    model_capability_revision_id: UUID,
    lifecycle: ModelLifecycle,
    reason: str,
) -> ModelPublicationState:
    """Record an explicit source-reviewed lifecycle change outside Manifest JSON."""
    if not reason.strip():
        raise ValueError("lifecycle change requires a reason")
    model = await session.get(ModelCapabilityRevision, model_capability_revision_id)
    if model is None or not model.source_snapshot_id:
        raise ValueError("lifecycle change requires a sourced model revision")
    state = await session.scalar(
        select(ModelPublicationState)
        .where(ModelPublicationState.model_capability_revision_id == model.id)
        .with_for_update()
    )
    if state is None or state.lifecycle == lifecycle:
        raise ValueError("model lifecycle is missing or unchanged")
    previous = state.lifecycle
    state.lifecycle = lifecycle
    state.updated_at = datetime.now(UTC)
    session.add(
        ModelPublicationEvent(
            model_capability_revision_id=model.id,
            from_lifecycle=previous,
            to_lifecycle=lifecycle,
            reason=reason.strip(),
        )
    )
    await session.flush()
    return state
