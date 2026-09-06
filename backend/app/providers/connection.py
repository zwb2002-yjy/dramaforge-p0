"""Provider connection DTO (V3 spec §23).

Transport is *which protocol*; Connection is *which base URL + credential this
user/workspace uses to reach it*. The DTO carries only ``credential_id`` — never
the secret itself (spec §23/§64). The persisted ORM lives in
:mod:`app.providers.models`; this module is the pure-DTO layer used by the V3
router/selector without touching ORM code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProviderConnection(BaseModel):
    id: str
    provider_id: str
    base_url: str
    credential_id: str | None = None
    region: str | None = None
    transport_overrides: dict[str, Any] = Field(default_factory=dict)
