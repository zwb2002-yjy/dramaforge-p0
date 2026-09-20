"""Shared reference intent: identity and purpose, independent of production implementation."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShotReferenceIntent(BaseModel):
    """One shot reference before capability translation (P4-02 input).

    Carries business purpose + artifact identity; never carries bytes/URLs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID | None = None
    purpose: str = Field(min_length=1, max_length=80)
    asset_version_id: UUID | None = None
    artifact_id: UUID | None = None
    resolution_mode: str = Field(default="current_formal", max_length=24)
    mime_type: str = Field(default="image/png", max_length=120)
    fingerprint: str | None = Field(default=None, max_length=128)
