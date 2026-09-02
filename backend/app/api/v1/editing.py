"""Project-scoped HTTP lifecycle for the Phase 9 EditingAdapter.

The editing session is a user-owned projection over formal production facts.
The API exposes only the existing adapter; it never edits Shot/Asset/Graph
truth and never renders media or calls a Provider.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.access.models import User
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.editing_suggestion import (
    EditingDirectorSuggestionCandidate,
    EditingDirectorSuggestionRequest,
    EditingDirectorSuggestionService,
    EditingProactiveSuggestionRequest,
)
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.editing.timeline_builder import build_edit_session_for_project
from app.shared.errors import ValidationAppError

router = APIRouter(tags=["editing"], dependencies=[Depends(require_selected_workspace)])

_DEFAULT_SESSION_NAME = "Long-form Edit"


class EditSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default=_DEFAULT_SESSION_NAME, min_length=1, max_length=200)


class EditTimelinePayload(BaseModel):
    """The adapter's editable timeline body, restricted to JSON-safe values."""

    model_config = ConfigDict(extra="forbid")

    clips: list[dict[str, JsonValue]] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EditTimelineUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline: EditTimelinePayload

    @model_validator(mode="after")
    def reject_production_lineage(self) -> EditTimelineUpdateRequest:
        _reject_production_lineage(self.timeline.model_dump(mode="json"))
        return self


class EditSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    project_id: UUID
    name: str
    status: str
    version: int
    timeline: dict[str, JsonValue]
    production_lineage: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime


class EditExportRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    format: str
    clip_count: int
    duration_seconds: float
    clips: list[dict[str, JsonValue]]
    production_lineage: dict[str, JsonValue]


class EditingDirectorSuggestionRead(BaseModel):
    """One persisted Director suggestion and its exact proposal item identity."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    item_id: UUID
    suggestion: EditingDirectorSuggestionCandidate


def _normalize_key(key: object) -> str:
    value = str(key).strip().replace("-", "_")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"_+", "_", value).lower()


def _reject_production_lineage(value: object, *, path: str = "timeline") -> None:
    """Keep production lineage immutable, including when nested in a clip."""

    if isinstance(value, dict):
        for key, nested in value.items():
            if _normalize_key(key) == "production_lineage":
                raise ValidationAppError(
                    "production_lineage is read-only and cannot be submitted",
                    details={"code": "EDIT_TIMELINE_LINEAGE_READ_ONLY", "path": path},
                )
            _reject_production_lineage(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_production_lineage(nested, path=f"{path}[{index}]")


def _edit_session_read(row: EditSession) -> EditSessionRead:
    return EditSessionRead(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        status=row.status,
        version=row.version,
        timeline=cast(dict[str, JsonValue], dict(row.timeline or {})),
        production_lineage=cast(dict[str, JsonValue], dict(row.production_lineage or {})),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _owned_session(
    *,
    project_id: UUID,
    session_id: UUID,
    user: User,
    session: SessionDep,
) -> EditSession:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await EditingAdapter(session).load_timeline(
        project_id=project_id,
        session_id=session_id,
    )


@router.post(
    "/projects/{project_id}/edit-sessions",
    response_model=EditSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_edit_session(
    project_id: UUID,
    body: EditSessionCreateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> EditSessionRead:
    """Build one edit timeline from the project's current formal production."""

    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    built = await build_edit_session_for_project(
        session,
        project_id=project_id,
        user_id=user.id,
        name=body.name,
    )
    # Load the just-flushed row before commit while the project RLS context is
    # active.  ``set_config(..., true)`` is transaction-local on PostgreSQL;
    # querying after commit would otherwise lose the project scope.
    row = await EditingAdapter(session).load_timeline(
        project_id=project_id,
        session_id=UUID(str(built["session_id"])),
    )
    await session.commit()
    return _edit_session_read(row)


@router.get(
    "/projects/{project_id}/edit-sessions/{session_id}",
    response_model=EditSessionRead,
)
async def get_edit_session(
    project_id: UUID,
    session_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> EditSessionRead:
    row = await _owned_session(
        project_id=project_id,
        session_id=session_id,
        user=user,
        session=session,
    )
    return _edit_session_read(row)


@router.patch(
    "/projects/{project_id}/edit-sessions/{session_id}/timeline",
    response_model=EditSessionRead,
)
async def save_edit_timeline(
    project_id: UUID,
    session_id: UUID,
    body: EditTimelineUpdateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> EditSessionRead:
    row = await _owned_session(
        project_id=project_id,
        session_id=session_id,
        user=user,
        session=session,
    )
    saved = await EditingAdapter(session).save_timeline(
        project_id=project_id,
        session_id=row.id,
        timeline=dict(body.timeline.model_dump(mode="json")),
    )
    await session.commit()
    return _edit_session_read(saved)


@router.post(
    "/projects/{project_id}/edit-sessions/{session_id}/director-suggestion",
    response_model=EditingDirectorSuggestionRead,
)
async def create_editing_director_suggestion(
    project_id: UUID,
    session_id: UUID,
    body: EditingDirectorSuggestionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> EditingDirectorSuggestionRead:
    """Generate one deterministic proposal-only suggestion for an EditSession.

    Route identifiers are the only target identity accepted here.  The service
    performs ownership, project/session scoping, both stale gates and strict
    candidate validation, then persists without applying the command or
    dispatching any provider/execution work.
    """

    result = await EditingDirectorSuggestionService(session).suggest(
        project_id=project_id,
        session_id=session_id,
        actor=user,
        request=body,
    )
    return EditingDirectorSuggestionRead(
        proposal_id=result.proposal_id,
        item_id=result.item_id,
        suggestion=result.candidate,
    )


@router.post(
    "/projects/{project_id}/edit-sessions/{session_id}/director-proactive-suggestion",
    response_model=EditingDirectorSuggestionRead,
)
async def create_editing_proactive_suggestion(
    project_id: UUID,
    session_id: UUID,
    body: EditingProactiveSuggestionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> EditingDirectorSuggestionRead:
    result = await EditingDirectorSuggestionService(session).suggest_proactive(
        project_id=project_id,
        session_id=session_id,
        actor=user,
        request=body,
    )
    return EditingDirectorSuggestionRead(
        proposal_id=result.proposal_id,
        item_id=result.item_id,
        suggestion=result.candidate,
    )


@router.get(
    "/projects/{project_id}/edit-sessions/{session_id}/export",
    response_model=EditExportRead,
)
async def export_edit_session(
    project_id: UUID,
    session_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> EditExportRead:
    # Ownership is checked before the adapter export. The adapter export is a
    # read-only manifest operation and does not load Artifact/Provider rows.
    await _owned_session(
        project_id=project_id,
        session_id=session_id,
        user=user,
        session=session,
    )
    manifest: dict[str, Any] = await EditingAdapter(session).export(
        project_id=project_id,
        session_id=session_id,
    )
    return EditExportRead.model_validate(manifest)


__all__ = [
    "EditExportRead",
    "EditSessionCreateRequest",
    "EditSessionRead",
    "EditTimelinePayload",
    "EditTimelineUpdateRequest",
    "EditingDirectorSuggestionRead",
    "router",
]
