"""Per-node model-profile snapshot helper (spec §22, M9).

Records *what the project planned* for a workflow node's slot into the NodeRun
snapshot — slot, resolved model, profile id/version, source. This is audit +
early-misconfiguration signal; the A+B binding / CapabilityRouter remain the
execution authority. The helper never raises: a node without a resolvable model
records an explicit ``model_id: None`` marker instead of blocking materialization
(spec §79 — a project that only configures LLM may still write scripts).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.slots import ModelSlot

# node_key → (slot, capability used for the planned snapshot).
NODE_SLOT_MAP: dict[str, tuple[ModelSlot, Capability]] = {
    "keyframe": (ModelSlot.VISUAL_KEYFRAME, Capability.IMAGE_GENERATE),
    # video.shot accepts multiple capabilities; the derived capability is
    # validated at execution (spec §10/§43). The snapshot uses i2v as the
    # representative planned capability.
    "video": (ModelSlot.VIDEO_SHOT, Capability.VIDEO_IMAGE_TO_VIDEO),
    "voice": (ModelSlot.AUDIO_TTS, Capability.AUDIO_TTS),
    "canonical": (ModelSlot.VISUAL_CHARACTER, Capability.IMAGE_GENERATE),
}


def node_slot_for(node_key: str) -> tuple[ModelSlot, Capability] | None:
    return NODE_SLOT_MAP.get(node_key)


def planned_capability_for_slot(slot: ModelSlot) -> Capability | None:
    """Capability a node plans for a slot (video.shot → image_to_video), used
    by previews that need the capability the pipeline will actually exercise."""
    for _node_key, (mapped_slot, capability) in NODE_SLOT_MAP.items():
        if mapped_slot == slot:
            return capability
    return None


def derive_video_capability(
    *,
    first_frame: bool,
    last_frame: bool,
    references: bool,
) -> Capability:
    """Derive the video capability a shot needs from its inputs (spec §43).

    Order is fixed: first+last → ``video.first_last_frame``, else first →
    ``video.image_to_video``, else references → ``video.reference_to_video``,
    else ``video.text_to_video``."""
    if first_frame and last_frame:
        return Capability.VIDEO_FIRST_LAST_FRAME
    if first_frame:
        return Capability.VIDEO_IMAGE_TO_VIDEO
    if references:
        return Capability.VIDEO_REFERENCE_TO_VIDEO
    return Capability.VIDEO_TEXT_TO_VIDEO


async def planned_node_model_profile(
    session: AsyncSession,
    *,
    project: Project,
    node_key: str,
    registry: Any | None = None,
    video_capability: Capability | None = None,
) -> dict[str, Any]:
    """Best-effort planned model for a node's slot. Never raises.

    ``video_capability`` lets callers pass the capability derived from the
    shot's actual inputs (spec §43); defaulting to i2v (P0 shots always have a
    keyframe as the first frame)."""
    pair = node_slot_for(node_key)
    if pair is None:
        return {}
    slot, capability = pair
    if node_key == "video" and video_capability is not None:
        capability = video_capability
    resolver = ModelBindingResolver(session, registry=registry)
    try:
        resolved = await resolver.resolve(
            workspace_id=project.workspace_id,
            project_id=project.id,
            slot=slot,
            capability=capability,
        )
    except Exception as exc:  # noqa: BLE001 - audit path, never block materialization
        return {
            "slot": str(slot),
            "capability": str(capability),
            "model_id": None,
            "source": "none",
            "error": str(exc)[:120],
        }
    return {
        "slot": str(resolved.slot),
        "capability": str(resolved.capability),
        "model_id": resolved.model_id,
        "source": resolved.source,
        "profile_id": str(resolved.profile_id) if resolved.profile_id is not None else None,
        "profile_version": resolved.profile_version,
        "native_options": resolved.native_options,
    }


async def workspace_id_for_project(session: AsyncSession, *, project_id: UUID) -> UUID | None:
    project = await session.get(Project, project_id)
    return project.workspace_id if project is not None else None
