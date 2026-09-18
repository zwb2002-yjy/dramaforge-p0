"""Per-shot 2D and rough-3D director board API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.production.models import DirectorBoardState
from app.shared.errors import ConflictError

router = APIRouter(tags=["director-board"], dependencies=[Depends(require_selected_workspace)])


class DirectorBoardBody(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    mode: str = Field(pattern="^(2d|rough_3d)$")
    camera: dict[str, object] = Field(default_factory=dict)
    characters: list[dict[str, object]] = Field(default_factory=list)
    scene: dict[str, object] = Field(default_factory=dict)


class DirectorBoardRead(BaseModel):
    id: UUID
    shot_id: UUID
    mode: str
    camera: dict[str, object]
    characters: list[dict[str, object]]
    scene: dict[str, object]
    version: int
    updated_at: datetime


def _read(row: DirectorBoardState) -> DirectorBoardRead:
    return DirectorBoardRead(
        id=row.id,
        shot_id=row.shot_id,
        mode=row.mode,
        camera=dict(row.camera),
        characters=list(row.characters),
        scene=dict(row.scene),
        version=row.version,
        updated_at=row.updated_at,
    )


@router.get(
    "/projects/{project_id}/shots/{shot_id}/director-board",
    response_model=DirectorBoardRead | None,
)
async def get_director_board(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> DirectorBoardRead | None:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    row = (
        await session.execute(
            select(DirectorBoardState).where(
                DirectorBoardState.project_id == project_id,
                DirectorBoardState.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    return _read(row) if row is not None else None


@router.put(
    "/projects/{project_id}/shots/{shot_id}/director-board",
    response_model=DirectorBoardRead,
)
async def save_director_board(
    project_id: UUID,
    shot_id: UUID,
    body: DirectorBoardBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorBoardRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    row = (
        await session.execute(
            select(DirectorBoardState)
            .where(
                DirectorBoardState.project_id == project_id,
                DirectorBoardState.shot_id == shot_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        if body.expected_version not in {None, 1}:
            raise ConflictError("director board version conflict")
        row = DirectorBoardState(
            project_id=project_id,
            shot_id=shot_id,
            mode=body.mode,
            camera=dict(body.camera),
            characters=list(body.characters),
            scene=dict(body.scene),
            version=1,
            updated_by=user.id,
            updated_at=now,
        )
        session.add(row)
    else:
        if body.expected_version is not None and row.version != body.expected_version:
            raise ConflictError(
                "director board version conflict",
                details={"expected_version": body.expected_version, "actual_version": row.version},
            )
        row.mode = body.mode
        row.camera = dict(body.camera)
        row.characters = list(body.characters)
        row.scene = dict(body.scene)
        row.version += 1
        row.updated_by = user.id
        row.updated_at = now
    await session.commit()
    return _read(row)
