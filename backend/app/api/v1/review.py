"""Professional shot review annotation API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.execution.models import Artifact
from app.shared.errors import ConflictError, NotFoundError

router = APIRouter(tags=["review"], dependencies=[Depends(require_selected_workspace)])


class AnnotationCreateBody(BaseModel):
    artifact_id: UUID | None = None
    target_kind: str | None = Field(
        default=None,
        pattern="^(shot|video_time|image_point|image_region)$",
    )
    time_start: Decimal | None = Field(default=None, ge=0)
    time_end: Decimal | None = Field(default=None, ge=0)
    x: Decimal | None = Field(default=None, ge=0, le=1)
    y: Decimal | None = Field(default=None, ge=0, le=1)
    width: Decimal | None = Field(default=None, ge=0, le=1)
    height: Decimal | None = Field(default=None, ge=0, le=1)
    note: str = Field(min_length=1, max_length=4000)
    severity: str = Field(default="note", pattern="^(note|warning|blocker)$")


class AnnotationRead(BaseModel):
    id: UUID
    shot_id: UUID
    artifact_id: UUID | None
    target_kind: str
    time_start: Decimal | None
    time_end: Decimal | None
    x: Decimal | None
    y: Decimal | None
    width: Decimal | None
    height: Decimal | None
    note: str
    severity: str
    status: str
    created_by: UUID
    created_at: datetime
    resolved_at: datetime | None


class AnnotationDecisionBody(BaseModel):
    status: str = Field(pattern="^(open|resolved)$")


def _read(row: ReviewAnnotation) -> AnnotationRead:
    return AnnotationRead(
        id=row.id,
        shot_id=row.shot_id,
        artifact_id=row.artifact_id,
        target_kind=row.target_kind,
        time_start=row.time_start,
        time_end=row.time_end,
        x=row.x,
        y=row.y,
        width=row.width,
        height=row.height,
        note=row.note,
        severity=row.severity,
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


@router.get(
    "/projects/{project_id}/shots/{shot_id}/annotations",
    response_model=list[AnnotationRead],
)
async def list_annotations(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[AnnotationRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = (
        (
            await session.execute(
                select(ReviewAnnotation)
                .where(
                    ReviewAnnotation.project_id == project_id,
                    ReviewAnnotation.shot_id == shot_id,
                )
                .order_by(ReviewAnnotation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_read(row) for row in rows]


@router.post(
    "/projects/{project_id}/shots/{shot_id}/annotations",
    response_model=AnnotationRead,
    status_code=201,
)
async def create_annotation(
    project_id: UUID,
    shot_id: UUID,
    body: AnnotationCreateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AnnotationRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise NotFoundError("shot not found")
    artifact = await session.get(Artifact, body.artifact_id) if body.artifact_id else None
    if body.artifact_id is not None and (
        artifact is None or artifact.project_id != project_id
    ):
        raise NotFoundError("annotation Artifact not found")
    if (
        body.time_start is not None
        and body.time_end is not None
        and body.time_end < body.time_start
    ):
        raise ConflictError("annotation time range is invalid")
    has_time = body.time_start is not None or body.time_end is not None
    has_point = body.x is not None or body.y is not None
    has_size = body.width is not None or body.height is not None
    target_kind = body.target_kind
    if target_kind is None:
        if has_size:
            target_kind = "image_region"
        elif has_point:
            target_kind = "image_point"
        elif has_time:
            target_kind = "video_time"
        else:
            target_kind = "shot"
    if target_kind == "shot" and (has_time or has_point or has_size):
        raise ConflictError("shot annotation cannot contain time or image coordinates")
    if target_kind == "video_time":
        if body.time_start is None or has_point or has_size:
            raise ConflictError("video annotation requires a time point or range only")
        if artifact is not None and artifact.artifact_type != "video":
            raise ConflictError("video annotation Artifact must be a video")
    if target_kind == "image_point":
        if body.x is None or body.y is None or has_size or has_time:
            raise ConflictError("image point annotation requires normalized x and y only")
        if artifact is None or artifact.artifact_type != "image":
            raise ConflictError("image annotation requires an image Artifact")
    if target_kind == "image_region":
        if (
            body.x is None
            or body.y is None
            or body.width is None
            or body.height is None
            or has_time
        ):
            raise ConflictError(
                "image region annotation requires normalized x, y, width and height"
            )
        if body.width <= 0 or body.height <= 0:
            raise ConflictError("image annotation region must have positive size")
        if body.x + body.width > 1 or body.y + body.height > 1:
            raise ConflictError("image annotation region exceeds image bounds")
        if artifact is None or artifact.artifact_type != "image":
            raise ConflictError("image annotation requires an image Artifact")
    row = ReviewAnnotation(
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
        target_kind=target_kind,
        time_start=body.time_start,
        time_end=body.time_end,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        note=body.note,
        severity=body.severity,
        created_by=user.id,
    )
    session.add(row)
    await session.commit()
    return _read(row)


@router.post(
    "/projects/{project_id}/shots/{shot_id}/annotations/{annotation_id}/decision",
    response_model=AnnotationRead,
)
async def decide_annotation(
    project_id: UUID,
    shot_id: UUID,
    annotation_id: UUID,
    body: AnnotationDecisionBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> AnnotationRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    row = (
        await session.execute(
            select(ReviewAnnotation)
            .where(
                ReviewAnnotation.id == annotation_id,
                ReviewAnnotation.project_id == project_id,
                ReviewAnnotation.shot_id == shot_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("review annotation not found")
    row.status = body.status
    row.resolved_at = datetime.now(UTC) if body.status == "resolved" else None
    await session.commit()
    return _read(row)
