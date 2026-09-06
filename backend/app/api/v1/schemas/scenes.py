"""API-boundary HTTP response schemas — scenes domain.

These are pure REST response DTOs. They are constructed/validated at the API
router boundary from the service/domain output; services remain unaware of them.
This module is deliberately separate from ``app/assets/schemas.py`` (which owns
persisted/domain serialized state such as ``SceneDesignState``).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.api.v1.schemas.common import ArtifactSummaryRead
from app.api.v1.schemas.workbench import BindingRead, ShotLiteRead


class SceneSummaryRead(BaseModel):
    id: UUID
    episode_id: UUID
    episode_number: int
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    version: int
    shot_count: int
    formal_keyframe_count: int
    formal_video_count: int
    risk_count: int
    representative_artifact: ArtifactSummaryRead | None


class SceneActionRead(BaseModel):
    id: UUID
    scene_number: int


class SceneCoreRead(BaseModel):
    id: UUID
    episode_id: UUID
    episode_number: int
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    version: int
    design_state: dict[str, object]


class SceneOperationPreviewRead(BaseModel):
    """Preview for split/merge destructive ops.

    Top-level fields are known-stable. ``affected`` is a shared sub-report
    envelope whose shape is the responsibility of the scene service; it is kept
    opaque here rather than forced into fabricated nested typed nodes.
    """

    scene_id: UUID
    at_shot_number: int | None = None
    new_scene_hint: str | None = None
    kept_scene_name: str | None = None
    absorbed_scene_name: str | None = None
    target_scene_id: UUID | None = None
    affected: dict[str, object]


class SceneWorkspaceRead(BaseModel):
    """Scene-scoped workspace snapshot.

    ``candidates`` / ``trace`` are genuinely dynamic experiment / node-run
    envelopes; they are documented opaque rather than modelled into a collection
    of invented nested schemas.
    """

    scene: SceneCoreRead
    shots: list[ShotLiteRead]
    references: dict[str, list[BindingRead]]
    candidates: dict[str, list[object]]
    trace: dict[str, list[object]]
