"""Pure, ORM-free construction of the facts frozen for one Director turn."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.providers.model_profiles.slots import ModelSlot


class DirectorContextSnapshot(BaseModel):
    """JSON snapshot passed to Turn identity and text request compilation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str
    project_id: str
    scope_type: str = Field(min_length=1, max_length=24)
    scope_entity_id: str
    slot: str
    input_versions: dict[str, object]
    intent: dict[str, object]
    context: dict[str, object]

    def as_json(self) -> dict[str, object]:
        """Return a detached JSON value so later ORM edits cannot mutate it."""

        return cast("dict[str, object]", json.loads(self.model_dump_json()))


class DirectorContextBuilder:
    """Compile caller-authorized facts without reading or advancing a Turn."""

    @staticmethod
    def build(
        *,
        workspace_id: UUID,
        project_id: UUID,
        scope_type: str,
        scope_entity_id: UUID,
        slot: ModelSlot,
        input_versions: dict[str, object],
        intent_snapshot: dict[str, object],
        context_payload: dict[str, object],
    ) -> DirectorContextSnapshot:
        return DirectorContextSnapshot(
            workspace_id=str(workspace_id),
            project_id=str(project_id),
            scope_type=scope_type,
            scope_entity_id=str(scope_entity_id),
            slot=str(slot),
            input_versions=json.loads(json.dumps(input_versions, ensure_ascii=False)),
            intent=json.loads(json.dumps(intent_snapshot, ensure_ascii=False)),
            context=json.loads(json.dumps(context_payload, ensure_ascii=False)),
        )


__all__ = ["DirectorContextBuilder", "DirectorContextSnapshot"]
