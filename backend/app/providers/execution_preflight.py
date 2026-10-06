"""Read-only preflight for the exact model and immutable provider identity."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from app.security.models import EncryptedProviderCredential


class ExecutionModelPreflightStageRead(BaseModel):
    """The concrete, executable model resolution for one production stage."""

    stage: str
    slot: str
    purpose: str
    ready: bool
    source: str
    requested_model_id: str | None
    resolved_model_id: str | None
    provider_model_binding_id: UUID | None
    reason: str | None


class ExecutionModelPreflightRead(BaseModel):
    project_id: UUID
    ready: bool
    stages: list[ExecutionModelPreflightStageRead]


async def resolve_execution_model_preflight(
    session: AsyncSession,
    *,
    project: Project,
) -> ExecutionModelPreflightRead:
    """Resolve the same model and revision prerequisites required by planning."""

    resolver = ExecutionModelResolver(session)
    contracts = (
        (
            "image_keyframe",
            ModelSlot.VISUAL_KEYFRAME,
            Capability.IMAGE_GENERATE,
            "keyframe",
            "text_to_image",
        ),
        (
            "video",
            ModelSlot.VIDEO_SHOT,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            "video",
            "first_frame",
        ),
    )
    stages: list[ExecutionModelPreflightStageRead] = []
    for stage, slot, capability, purpose, mode_id in contracts:
        resolved = await resolver.resolve(
            project=project,
            slot=slot,
            capability=capability,
            purpose=purpose,
            mode_id=mode_id,
        )
        reason = resolved.reason
        ready = resolved.status == "RESOLVED"
        if ready:
            connection = await session.get(ProviderConnection, resolved.provider_connection_id)
            if connection is None or connection.workspace_id != project.workspace_id:
                ready = False
                reason = "PROVIDER_CONNECTION_UNAVAILABLE"
            else:
                revision = await session.scalar(
                    select(ProviderConnectionRevision)
                    .where(ProviderConnectionRevision.connection_id == connection.id)
                    .order_by(ProviderConnectionRevision.revision_no.desc())
                    .limit(1)
                )
                if revision is None:
                    ready = False
                    reason = "PROVIDER_CONNECTION_REVISION_MISSING"
                else:
                    credential = await session.get(
                        EncryptedProviderCredential,
                        revision.credential_revision_id,
                    )
                    if (
                        credential is None
                        or credential.workspace_id != project.workspace_id
                        or revision.credential_revision_id != connection.credential_id
                    ):
                        ready = False
                        reason = "PROVIDER_CREDENTIAL_REVISION_MISSING"
        stages.append(
            ExecutionModelPreflightStageRead(
                stage=stage,
                slot=str(slot),
                purpose=purpose,
                ready=ready,
                source=resolved.source,
                requested_model_id=resolved.requested_model_id,
                resolved_model_id=resolved.resolved_model_id,
                provider_model_binding_id=resolved.provider_model_binding_id,
                reason=reason,
            )
        )
    return ExecutionModelPreflightRead(
        project_id=project.id,
        ready=all(stage.ready for stage in stages),
        stages=stages,
    )
