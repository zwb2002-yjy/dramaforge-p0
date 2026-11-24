"""Read the exact project model contract through the execution resolver."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.manifest import ModelCapabilityManifest, ModelManifest, to_v3_model_manifest
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver


async def resolve_project_keyframe_manifest(
    session: AsyncSession,
    *,
    project: Project,
) -> ModelManifest | None:
    resolution = await ExecutionModelResolver(session).resolve(
        project=project,
        slot=ModelSlot.VISUAL_KEYFRAME,
        capability=Capability.IMAGE_GENERATE,
        purpose="keyframe",
        mode_id=None,
    )
    if resolution.status != "RESOLVED" or resolution.catalog_entry_id is None:
        return None
    entry = await session.get(ModelCatalogEntry, resolution.catalog_entry_id)
    if entry is None or entry.lifecycle != "active":
        return None
    return to_v3_model_manifest(
        ModelCapabilityManifest.model_validate(entry.capability_manifest_json),
        transport_profile_id=entry.protocol_profile,
    )
