"""API schemas for model profiles (spec §34–§37)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ModelSlotRead(BaseModel):
    id: str
    display_name: str
    capabilities: list[str]
    description: str
    p0_scope: bool


class BindingInput(BaseModel):
    model_id: str = Field(min_length=1)
    native_options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class BindingRead(BaseModel):
    slot: str
    model_id: str
    native_options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    provider_id: str
    display_name: str
    configured: bool


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bindings: dict[str, BindingInput] = Field(default_factory=dict)
    is_default: bool = False
    # Snapshot another profile's bindings into this one (spec §54 Snapshot).
    copy_from: UUID | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    bindings: dict[str, BindingInput] | None = None
    is_default: bool | None = None
    expected_version: int | None = None


class SimpleModeApply(BaseModel):
    """Simple-mode batch patch (spec §30/§77). ``bindings`` stays the truth."""

    llm_model_id: str | None = None
    image_model_id: str | None = None
    video_model_id: str | None = None
    expected_version: int | None = None


class ProfileRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    name: str
    version: int
    is_default: bool
    bindings: dict[str, BindingRead] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProfileSummaryRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    name: str
    version: int
    is_default: bool
    binding_slots: list[str] = Field(default_factory=list)
    updated_at: datetime


class EffectiveBindingRead(BaseModel):
    slot: str
    capability: str
    model_id: str
    source: str
    profile_id: UUID | None = None
    profile_version: int | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)


class ProfileValidationIssue(BaseModel):
    code: str
    slot: str
    model_id: str
    message: str


class ProfileValidateRequest(BaseModel):
    bindings: dict[str, BindingInput] = Field(default_factory=dict)


class ProfileValidateResponse(BaseModel):
    valid: bool
    issues: list[ProfileValidationIssue] = Field(default_factory=list)
