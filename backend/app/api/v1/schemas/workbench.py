"""API-boundary HTTP response schemas — workbench / shot domain.

Pure REST response DTOs; constructed at the router boundary, not by services.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.api.v1.schemas.common import ArtifactSummaryRead


class BindingRead(BaseModel):
    id: UUID
    purpose: str
    label: str
    asset_id: UUID | None
    asset_version_id: UUID | None
    artifact_id: UUID | None
    resolution_mode: str
    stage: str
    version: int


class ShotLiteRead(BaseModel):
    id: UUID
    project_id: UUID
    scene_id: UUID
    shot_number: int
    shot_type: str
    camera_move: str
    visual_description: str
    dialogue: str
    duration_seconds: str
    status: str
    sort_order: int
    version: int
    director_state: dict[str, object]
    image_prompt: str
    video_prompt: str
    formal_keyframe_artifact_id: UUID | None
    formal_video_artifact_id: UUID | None
    formal_composite_artifact_id: UUID | None


class ShotSceneRead(BaseModel):
    id: UUID
    scene_number: int
    location_name: str
    time_of_day: str


class ShotPromptRead(BaseModel):
    visual_description: str
    image_prompt: str
    video_prompt: str
    director_state: dict[str, object]


class FormalArtifactsRead(BaseModel):
    keyframe: ArtifactSummaryRead | None
    video: ArtifactSummaryRead | None
    composite: ArtifactSummaryRead | None


class ShotWorkbenchRead(BaseModel):
    """Shot workbench aggregate for ``get_shot_workbench``.

    Known-stable fields are typed. ``candidates`` / ``trace`` /
    ``old_version_warnings`` are genuinely dynamic experiment / node-run /
    binding envelopes and are kept documented opaque rather than modelled into
    fabricated nested schemas.
    """

    shot: ShotLiteRead | None = None
    scene: ShotSceneRead | None = None
    prompt: ShotPromptRead | None = None
    references: list[BindingRead] = []
    formal_artifacts: FormalArtifactsRead | None = None
    candidates: list[dict[str, object]] = []
    trace: list[dict[str, object]] = []
    old_version_warnings: list[dict[str, object]] = []
