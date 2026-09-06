"""Domain (Pydantic) models for Production Model Profiles (spec §11–§17, §24).

These are pure data models with no ORM/IO. A profile only references
``model_id`` (never a provider protocol / credential — spec §13, §47, §134 rule
5/14); the :class:`ModelRegistry` owns provider/backend/capability knowledge.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.providers.capabilities import Capability
from app.providers.model_profiles.slots import ModelSlot


class GenerationPolicy(BaseModel):
    """Placeholder for P1 fallback policy (spec §87/§88).

    P0 selects only the default model — fallback is owned by
    ``GenerationPolicy`` / ``ModelSelector`` later, never by the Profile. Kept
    as a typed field so a future binding can carry it without a migration."""

    name: str = "default"


class ModelSlotBinding(BaseModel):
    """One slot→model assignment inside a profile (spec §12).

    ``native_options`` must still pass the target model's CapabilitySpec
    validation — never saved/executed unvalidated (spec §12, §134 rule 13)."""

    slot: ModelSlot
    model_id: str
    native_options: dict[str, Any] = Field(default_factory=dict)
    generation_policy: GenerationPolicy | None = None
    enabled: bool = True


class ResolvedModelBinding(BaseModel):
    """The effective model for one (slot, capability) after resolution
    (spec §16). Records *why* this model was chosen for audit."""

    slot: ModelSlot
    capability: Capability
    model_id: str
    source: Literal[
        "request_override",
        "project_profile",
        "workspace_profile",
        "system_default",
    ]
    profile_id: UUID | None = None
    profile_version: int | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)


class ModelProfileSnapshot(BaseModel):
    """Profile snapshot frozen when a Graph/Plan starts (spec §21/§92).

    Running graphs keep using this snapshot even if the profile changes —
    a started NodeRun must never silently switch models (spec §20)."""

    profile_id: UUID | None
    profile_version: int | None
    bindings: dict[ModelSlot, ResolvedModelBinding] = Field(default_factory=dict)


class ModelBackendBinding(BaseModel):
    """Execution-backend information for a model (spec §24–§28).

    Lives at the Registry-entry layer, not inside ``ModelManifest`` (Gap
    Analysis Q9): the manifest stays a pure capability contract; the backend
    tells the adapter how to execute (through LiteLLM, native, or local)."""

    kind: Literal["litellm", "native", "local"]
    gateway_model: str
    api_mode: Literal[
        "chat",
        "responses",
        "image_generation",
        "image_edit",
        "video_generation",
        "tts",
    ]
    provider_id: str
    model_family: str | None = None
    connection_id: str | None = None


class SimpleModeSelection(BaseModel):
    """Simple-mode LLM / Image / Video selection (spec §30/§77).

    Converted into a bindings patch by the service — never stored as a second
    source of truth."""

    llm_model_id: str | None = None
    image_model_id: str | None = None
    video_model_id: str | None = None
