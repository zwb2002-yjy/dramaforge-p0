"""Per-shot start / review / lock / re-run / manual media APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.execution import shot_review
from app.runtime.scheduler import AgentRunScheduler

router = APIRouter(tags=["shot-ops"])


class ShotActionBody(BaseModel):
    note: str = ""
    reason: str = ""
    locked: bool = True
    changed_node_key: str = "subtitle"
    node_keys: list[str] | None = None


class ShotStatusResponse(BaseModel):
    shot_id: str
    status: str
    locked: bool
    node_run_count: int
    failed_count: int
    guidance: dict | None
    pipeline: list[str]


class ShotActionResponse(BaseModel):
    shot_id: UUID
    status: str
    locked: bool
    message: str
    run_ids: list[UUID] = Field(default_factory=list)
    stale_nodes: list[str] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)


class ManualUploadResponse(BaseModel):
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    node_key: str


@router.get(
    "/projects/{project_id}/shots/{shot_id}/status",
    response_model=ShotStatusResponse,
)
async def shot_status(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ShotStatusResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    data = await shot_review.shot_status_summary(
        session, project_id=project_id, shot_id=shot_id
    )
    return ShotStatusResponse(**data)  # type: ignore[arg-type]


@router.post(
    "/projects/{project_id}/shots/{shot_id}/start",
    response_model=ShotActionResponse,
)
async def start_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotActionBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotActionResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    run_ids = await shot_review.start_shot_nodes(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        node_keys=body.node_keys,
    )
    jobs: list[str] = []
    sched = AgentRunScheduler(session)
    for rid in run_ids:
        try:
            jid = await sched.enqueue_node_run_only(rid)
            jobs.append(jid)
        except Exception as exc:  # noqa: BLE001
            jobs.append(f"error:{type(exc).__name__}")
    await session.commit()
    return ShotActionResponse(
        shot_id=shot_id,
        status="queued",
        locked=False,
        message="NodeRuns queued for Worker",
        run_ids=run_ids,
        job_ids=jobs,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/approve",
    response_model=ShotActionResponse,
)
async def approve_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotActionBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotActionResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    r = await shot_review.approve_shot(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        note=body.note,
    )
    await session.commit()
    return ShotActionResponse(
        shot_id=r.shot_id, status=r.status, locked=r.locked, message=r.message
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/reject",
    response_model=ShotActionResponse,
)
async def reject_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotActionBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotActionResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    r = await shot_review.reject_shot(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        reason=body.reason or body.note or "rejected",
    )
    await session.commit()
    return ShotActionResponse(
        shot_id=r.shot_id, status=r.status, locked=r.locked, message=r.message
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/lock",
    response_model=ShotActionResponse,
)
async def lock_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotActionBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotActionResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    r = await shot_review.lock_shot(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        locked=body.locked,
    )
    await session.commit()
    return ShotActionResponse(
        shot_id=r.shot_id, status=r.status, locked=r.locked, message=r.message
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/rerun",
    response_model=ShotActionResponse,
)
async def rerun_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotActionBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotActionResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    stale = await shot_review.local_rerun_from_node(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        changed_node_key=body.changed_node_key,
    )
    await session.commit()
    return ShotActionResponse(
        shot_id=shot_id,
        status="queued",
        locked=False,
        message=f"local re-run from {body.changed_node_key}",
        stale_nodes=stale,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/manual-media",
    response_model=ManualUploadResponse,
)
async def manual_media(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    node_key: str = Form(...),
    note: str = Form(""),
    file: UploadFile = File(...),
) -> ManualUploadResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    data = await file.read()
    mime = file.content_type or "application/octet-stream"
    art = await shot_review.upload_manual_media(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user.id,
        node_key=node_key,
        data=data,
        mime_type=mime,
        note=note,
    )
    await session.commit()
    return ManualUploadResponse(
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        node_key=node_key,
    )
