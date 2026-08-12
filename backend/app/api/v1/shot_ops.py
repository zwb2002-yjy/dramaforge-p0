"""Per-shot start / review / lock / re-run / manual media APIs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.legacy_guard import require_legacy_execution_allowed
from app.execution import shot_review
from app.runtime.scheduler import AgentRunScheduler
from app.shared.errors import ValidationAppError

router = APIRouter(
    tags=["shot-ops"], dependencies=[Depends(require_selected_workspace)]
)

ShotActionHandler = Callable[..., Awaitable[shot_review.ShotReviewResult]]
EnqueueActionResult = list[UUID] | tuple[list[str], list[UUID]]
EnqueueActionHandler = Callable[..., Awaitable[EnqueueActionResult]]


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
    guidance: dict[str, object] | None
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
    delete_reason: str | None = None


async def _enqueue_all(session: SessionDep, run_ids: list[UUID]) -> list[str]:
    """Commit-then-enqueue each run; raise if any fail (no silent 200+queued)."""
    jobs: list[str] = []
    errors: list[str] = []
    sched = AgentRunScheduler(session)
    for rid in run_ids:
        try:
            jid = await sched.enqueue_node_run_only(rid)
            if jid.startswith("local:"):
                errors.append(f"{rid}:local_forbidden")
                jobs.append("error:local_forbidden")
            else:
                jobs.append(jid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rid}:{type(exc).__name__}:{exc}")
            jobs.append(f"error:{type(exc).__name__}")
    if errors:
        raise ValidationAppError(
            "QUEUE_UNAVAILABLE: one or more NodeRuns failed Arq enqueue after commit; "
            f"failures={len(errors)}; jobs={jobs[:20]}"
        )
    return jobs


async def _run_shot_action(
    session: SessionDep,
    *,
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    handler: ShotActionHandler,
) -> ShotActionResponse:
    """Authorize, run a shot-review handler, commit, and build the response."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_shot_review"
    )
    r = await handler(session, project_id=project_id, shot_id=shot_id, user_id=user.id)
    await session.commit()
    return ShotActionResponse(
        shot_id=r.shot_id,
        status=r.status,
        locked=r.locked,
        message=r.message,
    )


async def _run_shot_action_with_enqueue(
    session: SessionDep,
    *,
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    message: str,
    handler: EnqueueActionHandler,
    changed_node_key: str | None = None,
) -> ShotActionResponse:
    """Authorize, run a handler that returns new run_ids, enqueue them."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_shot_media"
    )
    if changed_node_key:
        result = await handler(
            session,
            project_id=project_id,
            shot_id=shot_id,
            user_id=user.id,
            changed_node_key=changed_node_key,
        )
    else:
        result = await handler(
            session,
            project_id=project_id,
            shot_id=shot_id,
            user_id=user.id,
        )
    if isinstance(result, tuple):
        stale, run_ids = result
    else:
        stale, run_ids = [], result
    jobs = await _enqueue_all(session, run_ids)
    return ShotActionResponse(
        shot_id=shot_id,
        status="queued",
        locked=False,
        message=message,
        run_ids=run_ids,
        stale_nodes=stale,
        job_ids=jobs,
    )


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
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    data = await shot_review.shot_status_summary(
        session, project_id=project_id, shot_id=shot_id
    )
    return ShotStatusResponse.model_validate(data)


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
    return await _run_shot_action_with_enqueue(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user=user,
        message="NodeRuns committed and enqueued for Worker",
        handler=lambda s, **kw: shot_review.start_shot_nodes(
            s, node_keys=body.node_keys, **kw
        ),
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
    return await _run_shot_action(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user=user,
        handler=lambda s, **kw: shot_review.approve_shot(s, note=body.note, **kw),
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
    return await _run_shot_action(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user=user,
        handler=lambda s, **kw: shot_review.reject_shot(
            s, reason=body.reason or body.note or "rejected", **kw
        ),
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
    return await _run_shot_action(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user=user,
        handler=lambda s, **kw: shot_review.lock_shot(s, locked=body.locked, **kw),
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
    return await _run_shot_action_with_enqueue(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user=user,
        message=f"local re-run from {body.changed_node_key}",
        handler=shot_review.local_rerun_from_node,
        changed_node_key=body.changed_node_key,
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
    file: UploadFile = File(...),  # noqa: B008
) -> ManualUploadResponse:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_manual_media"
    )
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
        delete_reason=art.delete_reason,
    )
