"""Proposal-only Director Assistant endpoints.

The retired controlled workflow, budget, trial, batch, repair, and export
commands intentionally have no HTTP compatibility layer. Media execution is
owned by the canonical Scene/Shot Workbench APIs; this router only exposes the
read-only Shot suggestion seam.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.suggestion import (
    ShotDirectorSuggestion,
    ShotDirectorSuggestionRequest,
    ShotDirectorSuggestionService,
)
from app.shared.errors import ValidationAppError

router = APIRouter(tags=["director"], dependencies=[Depends(require_selected_workspace)])


@router.post(
    "/projects/{project_id}/director/shots/{shot_id}/suggestion",
    response_model=ShotDirectorSuggestion,
)
async def suggest_shot_design(
    project_id: UUID,
    shot_id: UUID,
    body: ShotDirectorSuggestionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotDirectorSuggestion:
    """Return one validated, non-persistent suggestion for the selected Shot."""

    if body.shot_id != shot_id:
        raise ValidationAppError(
            "shot id in the request body does not match the route",
            details={"code": "SHOT_SUGGESTION_SCOPE_MISMATCH"},
        )
    return await ShotDirectorSuggestionService(session).suggest(
        project_id=project_id,
        actor=user,
        request=body,
    )


__all__ = ["router", "suggest_shot_design"]
