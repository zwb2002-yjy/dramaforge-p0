"""Model selection: resolve an intent to a concrete binding, fail-closed.

``ModelSelectionService.select`` resolves an explicit model binding (stage A+B
scope) for a project, normalizes the intent, and evaluates the binding with the
SAME eligibility engine the candidates API uses. Ineligible models fail before
any paid request. The resulting :class:`SelectionPlan` is snapshotted onto
``ProviderOperation.selection_plan`` for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.eligibility import (
    IMAGE_GENERATE,
    VIDEO_GENERATE,
    evaluate_candidate,
)
from app.providers.intents import (
    ImageGenerationIntent,
    VideoGenerationIntentV1,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolution, ExecutionModelResolver
from app.providers.models import (
    ProviderConnection,
    ProviderModelBinding,
)
from app.providers.normalizer import (
    normalize_image,
    normalize_video,
)
from app.shared.errors import NotFoundError, ValidationAppError

_OPERATION_PURPOSE = {
    IMAGE_GENERATE: "keyframe",
    VIDEO_GENERATE: "video",
}

# A+B media purpose → Production Model Profile slot (spec §134 rule 6).
_PURPOSE_SLOT: dict[str, ModelSlot] = {
    "keyframe": ModelSlot.VISUAL_KEYFRAME,
    "video": ModelSlot.VIDEO_SHOT,
}


@dataclass(frozen=True)
class SelectionPlan:
    intent_hash: str
    purpose: str
    mode: str
    mode_id: str
    model_binding_id: UUID | None
    provider_type: str | None
    protocol_profile: str | None
    catalog_entry_id: UUID | None
    model_id: str | None
    invoke_model_value: str | None
    connection_id: UUID | None
    execution_model_resolution: ExecutionModelResolution
    supported_capabilities: list[str] = field(default_factory=list)
    met_requirements: list[str] = field(default_factory=list)
    unmet_requirements: list[str] = field(default_factory=list)
    dropped_preferences: list[str] = field(default_factory=list)
    parameter_substitutions: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, bool] = field(default_factory=dict)
    estimated_cost: dict[str, Any] | None = None
    manifest_hash: str | None = None
    compiled_by: str | None = None


def _intent_hash(intent: Any) -> str:
    raw = json.dumps(
        intent.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolution_capability(*, purpose: str, reference_roles: frozenset[str]) -> Capability:
    """Use the concrete input shape when freezing the business capability."""
    if purpose == "keyframe":
        return Capability.IMAGE_GENERATE
    if {"first_frame", "last_frame"} <= reference_roles:
        return Capability.VIDEO_FIRST_LAST_FRAME
    if "first_frame" in reference_roles:
        return Capability.VIDEO_IMAGE_TO_VIDEO
    if reference_roles:
        return Capability.VIDEO_REFERENCE_TO_VIDEO
    return Capability.VIDEO_TEXT_TO_VIDEO


def _video_mode_id(intent: VideoGenerationIntentV1) -> str:
    if intent.mode_id:
        return intent.mode_id
    roles = {str(reference.role) for reference in intent.references}
    if {"first_frame", "last_frame"} <= roles:
        return "first_last_frame"
    if roles & {"reference_image", "reference_video", "reference_audio"}:
        return "omni_reference"
    if "first_frame" in roles:
        return "first_frame"
    return "text_to_video"


def _image_mode_id(intent: ImageGenerationIntent) -> str:
    if intent.mode_id:
        return intent.mode_id
    return "reference_image" if intent.reference_artifact_id is not None else "text_to_image"


class ModelSelectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def select_video(
        self,
        *,
        project: Project,
        intent: VideoGenerationIntentV1,
    ) -> SelectionPlan:
        normalized = normalize_video(intent)
        if not normalized.ok:
            raise ValidationAppError(
                "video intent cannot be normalized",
                details={"code": "INTENT_NORMALIZATION_FAILED", "errors": normalized.errors},
            )
        return await self._resolve(
            project=project,
            operation=VIDEO_GENERATE,
            purpose="video",
            intent_hash=_intent_hash(intent),
            mode=intent.selection.mode,
            mode_id=_video_mode_id(intent),
            requested_binding_id=intent.selection.model_binding_id,
            required_capabilities=normalized.required_capabilities,
            reference_roles=normalized.reference_roles,
            preferred_capabilities=normalized.preferred_capabilities,
        )

    async def select_image(
        self,
        *,
        project: Project,
        intent: ImageGenerationIntent,
    ) -> SelectionPlan:
        normalized = normalize_image(intent)
        if not normalized.ok:
            raise ValidationAppError(
                "image intent cannot be normalized",
                details={"code": "INTENT_NORMALIZATION_FAILED", "errors": normalized.errors},
            )
        return await self._resolve(
            project=project,
            operation=IMAGE_GENERATE,
            purpose="keyframe",
            intent_hash=_intent_hash(intent),
            mode=intent.selection.mode,
            mode_id=_image_mode_id(intent),
            requested_binding_id=intent.selection.model_binding_id,
            required_capabilities=normalized.required_capabilities,
            reference_roles=normalized.reference_roles,
            preferred_capabilities=normalized.preferred_capabilities,
        )

    async def _resolve(
        self,
        *,
        project: Project,
        operation: str,
        purpose: str,
        intent_hash: str,
        mode: str,
        mode_id: str,
        requested_binding_id: UUID | None,
        required_capabilities: frozenset[str],
        reference_roles: frozenset[str],
        preferred_capabilities: frozenset[str],
    ) -> SelectionPlan:
        resolution = await ExecutionModelResolver(self._session).resolve(
            project=project,
            slot=_PURPOSE_SLOT[purpose],
            capability=_resolution_capability(
                purpose=purpose,
                reference_roles=reference_roles,
            ),
            purpose=purpose,
            mode_id=mode_id,
            requested_binding_id=requested_binding_id,
        )
        if resolution.status != "RESOLVED" or resolution.provider_model_binding_id is None:
            raise ValidationAppError(
                "selected execution model is unavailable",
                details={
                    "code": resolution.reason or "MODEL_BINDING_UNAVAILABLE",
                    "requested_model_id": resolution.requested_model_id,
                    "source": resolution.source,
                },
            )
        binding = await self._session.get(
            ProviderModelBinding, resolution.provider_model_binding_id
        )
        if binding is None:
            raise NotFoundError("resolved provider model binding not found")
        connection = await self._session.get(ProviderConnection, binding.connection_id)
        if connection is None:
            raise NotFoundError("provider connection not found")
        entry = (
            await self._session.get(ModelCatalogEntry, binding.catalog_entry_id)
            if binding.catalog_entry_id is not None
            else None
        )
        evaluation = await evaluate_candidate(
            self._session,
            binding=binding,
            connection=connection,
            catalog_entry=entry,
            operation=operation,
            required_capabilities=required_capabilities,
            reference_roles=reference_roles,
            preferred_capabilities=preferred_capabilities,
        )
        remaining_issues = evaluation.issues
        if remaining_issues:
            raise ValidationAppError(
                "selected model binding is not eligible for this intent",
                details={
                    "code": "MODEL_INELIGIBLE",
                    "issues": [issue.code for issue in remaining_issues],
                },
            )
        manifest = ModelCapabilityManifest.model_validate(
            entry.capability_manifest_json
        ) if entry is not None else None
        supported = set(evaluation.supported_capabilities)
        return SelectionPlan(
            intent_hash=intent_hash,
            purpose=purpose,
            mode=mode,
            mode_id=mode_id,
            model_binding_id=binding.id,
            provider_type=connection.provider_type,
            protocol_profile=connection.protocol_profile,
            catalog_entry_id=entry.id if entry is not None else None,
            model_id=binding.model_id,
            invoke_model_value=binding.invoke_model_value,
            connection_id=connection.id,
            execution_model_resolution=resolution,
            supported_capabilities=sorted(supported),
            met_requirements=sorted(required_capabilities & supported),
            unmet_requirements=sorted(required_capabilities - supported),
            dropped_preferences=evaluation.unmet_preferences,
            evidence={
                **evaluation.evidence,
            },
            manifest_hash=entry.contract_manifest_hash if entry is not None else None,
            compiled_by=manifest.catalog_source if manifest is not None else None,
        )
