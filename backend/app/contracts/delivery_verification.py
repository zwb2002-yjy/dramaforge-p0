"""Frozen references for checking an approved MP4/SRT delivery without creating work."""

from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class DeliveryPackage(BaseModel):
    episode_id: UUID | None
    episode_number: int | None = Field(default=None, strict=True, ge=1)
    edit_session_id: UUID | None = None
    timeline_version: int | None = None
    timeline_hash: str | None = None
    export_id: UUID | None = None
    render_node_run_id: UUID | None = None
    mp4_artifact_id: UUID | None = None
    srt_artifact_id: UUID | None = None
    mp4_content_hash: str | None = None
    srt_content_hash: str | None = None
    blockers: list[str]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeliveryTarget(_Frozen):
    episode_id: UUID | None
    episode_number: int | None = Field(default=None, strict=True, ge=1)
    edit_session_id: UUID | None = None
    timeline_version: int | None = Field(default=None, strict=True, ge=1)
    export_id: UUID | None = None

    @model_validator(mode="after")
    def version_owner(self) -> Self:
        if self.timeline_version is not None and self.edit_session_id is None:
            raise ValueError("a timeline version must name its edit session")
        return self


class EpisodeDeliveryGoal(_Frozen):
    rule_id: Literal["episode_export_ready_v1"]
    target: DeliveryTarget

    @model_validator(mode="after")
    def scoped(self) -> Self:
        if self.target.episode_id is None:
            raise ValueError("an episode goal needs a specific episode")
        return self


class ProjectDeliveryGoal(_Frozen):
    rule_id: Literal["project_delivery_ready_v1"]
    work_type: Literal["serial_comic", "single_comic", "animation_promo"]
    targets: list[DeliveryTarget] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        ids = {target.episode_id for target in self.targets}
        if len(ids) != len(self.targets):
            raise ValueError("duplicate episode target")
        if self.work_type == "serial_comic":
            if len(ids) < 2 or None in ids:
                raise ValueError("a series needs at least two distinct episode targets")
        elif len(ids) != 1 or (self.work_type == "single_comic" and None in ids):
            raise ValueError("work type does not match delivery scope")
        return self


class FlowCompletionGoal(_Frozen):
    rule_id: Literal[
        "all_required_steps_succeeded", "no_unresolved_external", "business_flow_completed_v1"
    ]


CompletionGoal = Annotated[
    EpisodeDeliveryGoal | ProjectDeliveryGoal | FlowCompletionGoal,
    Field(discriminator="rule_id"),
]
COMPLETION_RULES: TypeAdapter[list[CompletionGoal]] = TypeAdapter(
    Annotated[list[CompletionGoal], Field(min_length=1)]
)


class DeliveryVerifier(Protocol):
    async def __call__(
        self,
        *,
        project_id: UUID,
        episode_id: UUID | None,
        edit_session_id: UUID | None,
        timeline_version: int | None,
        export_id: UUID | None,
    ) -> DeliveryPackage: ...
