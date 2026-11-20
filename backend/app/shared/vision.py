"""Owner-selected project media and the deterministic transformation for a vision turn."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_VISION_BYTES = 4 * 1024 * 1024
MAX_VISION_PARTS = 4
Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class VisionTransform(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    crop: tuple[Coordinate, Coordinate, Coordinate, Coordinate] | None = None
    frame_time_ms: int | None = Field(default=None, strict=True, ge=0)
    max_edge: int = Field(default=1024, strict=True, ge=1, le=1024)

    @model_validator(mode="after")
    def ordered_crop(self) -> Self:
        if self.crop:
            left, top, right, bottom = self.crop
            if right <= left or bottom <= top:
                raise ValueError("crop must contain a positive area")
        return self


class _VisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform: VisionTransform = Field(default_factory=VisionTransform)


class ArtifactVisionInput(_VisionInput):
    kind: Literal["artifact"]
    artifact_id: UUID


class FileVisionInput(_VisionInput):
    kind: Literal["file"]
    file_revision_id: UUID
    source_fragment_id: UUID


SourceMediaInput = Annotated[ArtifactVisionInput | FileVisionInput, Field(discriminator="kind")]
