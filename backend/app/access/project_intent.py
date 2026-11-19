"""Typed project intent; legacy unconfirmed type is never an inferred default."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, model_validator

WorkType = Literal["animation_promo", "single_comic", "serial_comic"]


def _decimal_text(value: object) -> object:
    if value is not None and not isinstance(value, (str, Decimal)):
        raise ValueError("planned_duration_seconds must be a decimal string")
    return value


DurationSeconds = Annotated[
    Decimal, BeforeValidator(_decimal_text),
    Field(gt=0, lt=Decimal("1000000000"), max_digits=12, decimal_places=3, allow_inf_nan=False),
    WithJsonSchema({"type": "string", "format": "decimal"}, mode="validation"),
]


class ProjectIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    work_type: WorkType | None = None
    creative_goal: str = Field(default="", max_length=16000)
    audience: str = Field(default="", max_length=2000)
    planned_duration_seconds: DurationSeconds | None = None
    planned_episode_count: int | None = Field(
        default=None, strict=True, ge=1, le=2147483647,
    )

    @model_validator(mode="after")
    def check_episode_plan(self) -> Self:
        count = self.planned_episode_count
        if count is not None:
            if self.work_type == "animation_promo":
                raise ValueError("animation_promo does not have an episode count plan")
            if self.work_type == "single_comic" and count != 1:
                raise ValueError("single_comic has exactly one episode")
            if self.work_type == "serial_comic" and count < 2:
                raise ValueError("serial_comic requires at least two planned episodes")
        return self


class ProjectUpdateImpact(BaseModel):
    """Read-only current structure, not an authorization or saved business fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    project_version: int
    episode_count: int
    can_apply: bool
    blockers: list[str]
    affected_export_id: UUID | None = None
