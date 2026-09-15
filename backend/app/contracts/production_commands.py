"""Validated stage command bodies shared by HTTP and application callers.

Identity is supplied separately by the authenticated application, never by the
model-generated body. Director callers must obtain a persisted grant before
using the production application; this schema itself is not an authorization.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.production.reference_intents import ShotReferenceIntent


class ExecutionPlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["image_keyframe", "video"]
    prompt: str = Field(min_length=1, max_length=20000)
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    mode_id: str = Field(min_length=1, max_length=120)
    requested_model_id: str | None = None
    requested_binding_id: UUID | None = None
    accept_approximations: bool = False
    references: list[ShotReferenceIntent] = Field(default_factory=list)
    expected_shot_version: int = Field(ge=1)


class ExecutionBody(ExecutionPlanBody):
    plan_fingerprint: str = Field(min_length=64, max_length=64)
    accepted_approximations: list[str] = Field(default_factory=list)


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_run_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    status: str
    plan_fingerprint: str
