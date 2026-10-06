"""Unified creative-intent domain models for image/video generation.

Stage A+B scope is intentionally narrow: only ``keyframe`` (image.generate) and
``shot_video`` (video.generate) purposes and the ``explicit_binding`` selection
mode are open. ``auto`` / ``project_default`` / ``preview`` / ``variant`` are
declared for forward compatibility but rejected by the normalizer/selector.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.providers.reference_roles import ReferenceRoleValue

# Backward-compatible type alias; canonical ownership lives in reference_roles.
ReferenceRole = ReferenceRoleValue


class VideoOutputIntent(BaseModel):
    aspect_ratio: Literal["9:16", "16:9", "1:1", "adaptive"] | None = None
    duration_seconds: int | None = None
    resolution: str | None = None
    generate_audio: bool | None = None
    seed: int | None = None


class AllowedOutputSubstitution(BaseModel):
    field: Literal["duration_seconds", "resolution", "aspect_ratio"]
    policy: Literal["nearest", "at_least", "at_most", "provider_default"]
    max_numeric_delta: float | None = None


class ArtifactReferenceIntent(BaseModel):
    artifact_id: UUID
    role: ReferenceRoleValue
    required: bool = True


class VideoRequirements(BaseModel):
    required_capabilities: set[str] = Field(default_factory=set)
    preserve_character_identity: bool = False
    forbid_model_fallback: bool = True


class VideoPreferences(BaseModel):
    preferred_capabilities: set[str] = Field(default_factory=set)
    camera_motion: Literal["static", "subtle", "dynamic"] | None = None
    quality_tier: Literal["draft", "standard", "high"] | None = None
    allowed_output_substitutions: list[AllowedOutputSubstitution] = Field(
        default_factory=list
    )


class ModelSelectionIntent(BaseModel):
    mode: Literal["project_default", "explicit_binding", "auto"]
    model_binding_id: UUID | None = None


class VideoGenerationIntentV1(BaseModel):
    operation: Literal["video.generate"] = "video.generate"
    purpose: Literal["shot_video", "preview", "variant"] = "shot_video"
    prompt: str
    output: VideoOutputIntent = Field(default_factory=VideoOutputIntent)
    references: list[ArtifactReferenceIntent] = Field(default_factory=list)
    requirements: VideoRequirements = Field(default_factory=VideoRequirements)
    preferences: VideoPreferences = Field(default_factory=VideoPreferences)
    mode_id: str | None = None
    selection: ModelSelectionIntent


class ImageGenerationIntent(BaseModel):
    operation: Literal["image.generate"] = "image.generate"
    purpose: Literal["keyframe"] = "keyframe"
    prompt: str
    size: str | None = None
    aspect_ratio: Literal["9:16", "16:9", "1:1"] | None = None
    seed: int | None = None
    reference_artifact_id: UUID | None = None
    # Ordered protocol input for new multi-reference contracts. The existing
    # Workbench keeps using the single-reference field until its product policy
    # explicitly opens multiple images.
    reference_artifact_ids: list[UUID] = Field(default_factory=list)
    reference_fingerprint: str | None = None
    reference_mime: str | None = None
    requirements: VideoRequirements = Field(default_factory=VideoRequirements)
    preferences: VideoPreferences = Field(default_factory=VideoPreferences)
    mode_id: str | None = None
    selection: ModelSelectionIntent

    def selected_reference_ids(self) -> list[UUID]:
        if self.reference_artifact_id is not None and self.reference_artifact_ids:
            raise ValueError("image intent cannot mix single and multiple reference fields")
        if self.reference_artifact_ids:
            selected = list(self.reference_artifact_ids)
        elif self.reference_artifact_id is not None:
            selected = [self.reference_artifact_id]
        else:
            selected = []
        if len(selected) != len(set(selected)):
            raise ValueError("image intent repeats a reference artifact")
        return selected
