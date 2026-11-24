"""Neutral, read-only media inspection port for the Director tool allowlist."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.contracts.shot_reference import ShotReferenceIntent

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MediaStage = Literal["image_keyframe", "video"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelToolScope(_Strict):
    actor_id: UUID
    workspace_id: UUID
    project_id: UUID
    scope_type: Literal["project", "story", "scene", "shot"]
    scope_entity_id: UUID
    expected_versions: dict[str, int] = Field(default_factory=dict, max_length=100)


class ModelCapabilitiesInput(_Strict):
    stage: MediaStage
    mode_id: str | None = Field(default=None, min_length=1, max_length=120)


class ModelCompilePreviewInput(_Strict):
    shot_id: UUID
    expected_shot_version: int = Field(ge=1, strict=True)
    stage: MediaStage
    mode_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=20000)
    requested_binding_id: UUID
    expected_identity_hash: Digest
    expected_manifest_hash: Digest
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    references: list[ShotReferenceIntent] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def bounded_input(self) -> Self:
        value = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, allow_nan=False)
        if len(value.encode("utf-8")) > 65536:
            raise ValueError("compile preview input exceeds 64 KiB")
        return self


class _Result(_Strict):
    observed_versions: dict[str, int]
    provenance: dict[str, str]
    account_verified: Literal[False] = False
    transport_verified: Literal[False] = False

    @model_validator(mode="after")
    def bounded_output(self) -> Self:
        value = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, allow_nan=False)
        if len(value.encode("utf-8")) > 20480:
            raise ValueError("model tool output exceeds 20 KiB; narrow the selected mode")
        return self


class ModelCapabilitiesRead(_Result):
    stage: MediaStage
    mode_id: str | None
    binding_id: UUID
    connection_revision_id: UUID
    model_id: str
    model_revision: str | None
    manifest_hash: Digest
    identity_hash: Digest
    binding_status: Literal["RESOLVED", "UNAVAILABLE"]
    binding_reason: str | None
    capabilities: dict[str, JsonValue]
    controls: dict[str, Literal["native", "prompt_only", "unsupported", "unknown"]]
    generation_options: dict[str, JsonValue]
    limitations: list[str]


class ModelCompilePreviewRead(_Result):
    stage: MediaStage
    mode_id: str
    binding_id: UUID
    connection_revision_id: UUID
    model_id: str
    model_revision: str | None
    manifest_hash: Digest
    identity_hash: Digest
    plan_fingerprint: Digest
    snapshot_hash: Digest
    prompt_hash: Digest
    semantic_hash: Digest
    wire_fingerprint: Digest | None
    readiness: Literal["contract_validated", "blocked"]
    requested_options: dict[str, JsonValue]
    effective_options: dict[str, JsonValue]
    references: list[dict[str, JsonValue]]
    errors: list[str]
    warnings: list[str]


class ModelToolsPort(Protocol):
    async def inspect(
        self,
        *,
        scope: ModelToolScope,
        request: ModelCapabilitiesInput,
    ) -> ModelCapabilitiesRead: ...

    async def preview(
        self,
        *,
        scope: ModelToolScope,
        request: ModelCompilePreviewInput,
    ) -> ModelCompilePreviewRead: ...
