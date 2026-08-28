"""Shared API-boundary HTTP response schemas (across scenes + workbench)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ArtifactSummaryRead(BaseModel):
    id: UUID
    artifact_type: str
    mime_type: str
    content_hash: str
    byte_size: int
    storage_state: str
