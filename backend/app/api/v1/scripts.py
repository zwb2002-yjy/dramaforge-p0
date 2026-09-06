"""Script import and professional shot canvas API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import (
    CanvasRevision,
    Episode,
    Scene,
    ScriptDocument,
    Shot,
    ShotChangeProposal,
)
from app.assets.script_import import import_script
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

router = APIRouter(tags=["scripts"], dependencies=[Depends(require_selected_workspace)])


class ScriptImportBody(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    text: str = Field(min_length=1)


class ScriptImportResponse(BaseModel):
    script_document_id: UUID
    episode_id: UUID
    scene_count: int
    shot_count: int
    shot_ids: list[UUID]
    content_hash: str


class ShotRead(BaseModel):
    id: UUID
    scene_id: UUID
    shot_number: int
    shot_type: str
    camera_move: str
    visual_description: str
    dialogue: str
    duration_seconds: Decimal
    sort_order: int
    status: str
    version: int


class SceneRead(BaseModel):
    id: UUID
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    shot_count: int
    version: int


class EpisodeRead(BaseModel):
    id: UUID
    episode_number: int
    title: str | None
    synopsis: str
    scenes: list[SceneRead]
    version: int


class ScriptDocumentRead(BaseModel):
    script_document_id: UUID
    filename: str
    content_hash: str
    format: str
    raw_text: str
    version: int


class ScriptWorkspaceRead(BaseModel):
    document: ScriptDocumentRead | None
    episodes: list[EpisodeRead]


class CanvasRevisionRead(BaseModel):
    id: UUID
    revision_number: int
    base_shot_version: int
    visual_description: str
    shot_type: str
    camera_move: str
    dialogue: str
    duration_seconds: Decimal
    source: str
    created_at: datetime

class ShotChangeProposalCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=4000)
    expected_version: int = Field(ge=1)
    replacement_payload: dict[str, object]
    affected_node_keys: list[str] = Field(default_factory=list, max_length=20)
    reusable_artifact_ids: list[str] = Field(default_factory=list, max_length=50)


class ShotChangePayload(BaseModel):
    """Strict, validated *partial* replacement of the Shot canvas.

    ``extra="forbid"`` so an unknown field fails closed rather than being
    silently ignored. Each canvas field is optional — a proposal may override
    only a subset (e.g. just ``visual_description``); apply computes the complete
    resulting state as current Shot + present overrides. Field constraints mirror
    ``ShotCanvasUpdateBody``. Validated at proposal creation and re-validated at
    confirm/apply time (the persisted JSON may predate a schema change).
    """

    model_config = ConfigDict(extra="forbid")

    visual_description: str | None = Field(default=None, min_length=1)
    shot_type: str | None = Field(default=None, min_length=1, max_length=40)
    camera_move: str | None = Field(default=None, min_length=1, max_length=80)
    dialogue: str | None = None
    duration_seconds: Decimal | None = Field(default=None, gt=0, le=30, decimal_places=3)


class ShotChangeProposalRead(BaseModel):
    id: UUID
    shot_id: UUID
    summary: str
    base_shot_version: int
    replacement_payload: dict[str, object]
    affected_node_keys: list[str]
    reusable_artifact_ids: list[str]
    status: str
    confirmed_revision_id: UUID | None
    created_at: datetime
    confirmed_at: datetime | None


class ShotChangeProposalResult(BaseModel):
    proposal: ShotChangeProposalRead
    impact: dict[str, object]

class ShotCanvasUpdateBody(BaseModel):
    expected_version: int = Field(ge=1)
    visual_description: str = Field(min_length=1)
    shot_type: str = Field(min_length=1, max_length=40)
    camera_move: str = Field(min_length=1, max_length=80)
    dialogue: str = ""
    duration_seconds: Decimal | None = Field(default=None, gt=0, le=30, decimal_places=3)
    source: str = Field(default="user", pattern="^(user|assistant)$")


class ShotCanvasUpdateResponse(BaseModel):
    shot: ShotRead
    revision_id: UUID
    revision_number: int


def _proposal_read(proposal: ShotChangeProposal) -> ShotChangeProposalRead:
    return ShotChangeProposalRead(
        id=proposal.id,
        shot_id=proposal.shot_id,
        summary=proposal.summary,
        base_shot_version=proposal.base_shot_version,
        replacement_payload=proposal.replacement_payload,
        affected_node_keys=list(proposal.affected_node_keys),
        reusable_artifact_ids=list(proposal.reusable_artifact_ids),
        status=proposal.status,
        confirmed_revision_id=proposal.confirmed_revision_id,
        created_at=proposal.created_at,
        confirmed_at=proposal.confirmed_at,
    )

def _shot_read(shot: Shot) -> ShotRead:
    return ShotRead(
        id=shot.id,
        scene_id=shot.scene_id,
        shot_number=shot.shot_number,
        shot_type=shot.shot_type,
        camera_move=shot.camera_move,
        visual_description=shot.visual_description,
        dialogue=shot.dialogue,
        duration_seconds=shot.duration_seconds,
        sort_order=shot.sort_order,
        status=shot.status,
        version=shot.version,
    )


@router.get("/projects/{project_id}/script", response_model=ScriptWorkspaceRead)
async def get_project_script(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ScriptWorkspaceRead:
    """Return the Script workspace for reading (raw text + Episodes/Scenes).

    This is a read-only workspace. It returns HTTP 200 with ``document=None`` and
    ``episodes=[]`` when no script has been imported yet — the frontend treats
    that as the empty state, not an error. Safe script replacement / re-parse
    (which must reconcile stale Scene/Shot rows) is a later Story-domain task and
    is NOT satisfied by re-POSTing ``/scripts/import`` here.
    """
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)

    doc = (
        await session.execute(
            select(ScriptDocument)
            .where(ScriptDocument.project_id == project_id)
            .order_by(ScriptDocument.created_at.desc(), ScriptDocument.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    episode_rows = (
        await session.execute(
            select(Episode)
            .where(Episode.project_id == project_id)
            .order_by(Episode.episode_number, Episode.id)
        )
    ).scalars().all()

    episodes: list[EpisodeRead] = []
    for episode in episode_rows:
        scene_rows = (
            await session.execute(
                select(Scene)
                .where(Scene.episode_id == episode.id)
                .order_by(Scene.scene_number, Scene.id)
            )
        ).scalars().all()
        scenes: list[SceneRead] = []
        for scene in scene_rows:
            shot_count = (
                await session.execute(
                    select(func.count(Shot.id)).where(Shot.scene_id == scene.id)
                )
            ).scalar_one()
            scenes.append(
                SceneRead(
                    id=scene.id,
                    scene_number=scene.scene_number,
                    location_name=scene.location_name,
                    time_of_day=scene.time_of_day,
                    synopsis=scene.synopsis,
                    shot_count=shot_count,
                    version=scene.version,
                )
            )
        episodes.append(
            EpisodeRead(
                id=episode.id,
                episode_number=episode.episode_number,
                title=episode.title,
                synopsis=episode.synopsis,
                scenes=scenes,
                version=episode.version,
            )
        )

    document = (
        ScriptDocumentRead(
            script_document_id=doc.id,
            filename=doc.filename,
            content_hash=doc.content_hash,
            format=doc.format,
            raw_text=doc.raw_text,
            version=doc.version,
        )
        if doc is not None
        else None
    )
    return ScriptWorkspaceRead(document=document, episodes=episodes)


@router.post("/projects/{project_id}/scripts/import", response_model=ScriptImportResponse)
async def import_project_script(
    project_id: UUID,
    body: ScriptImportBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ScriptImportResponse:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    result = await import_script(
        session,
        project_id=project_id,
        actor_id=user.id,
        filename=body.filename,
        text=body.text,
        actor=user,
    )
    # Canonical references are intentionally not fabricated during import.
    await session.commit()
    return ScriptImportResponse(
        script_document_id=result.script_document_id,
        episode_id=result.episode_id,
        scene_count=result.scene_count,
        shot_count=result.shot_count,
        shot_ids=result.shot_ids,
        content_hash=result.content_hash,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/change-proposals",
    response_model=ShotChangeProposalResult,
    status_code=201,
)
async def create_shot_change_proposal(
    project_id: UUID,
    shot_id: UUID,
    body: ShotChangeProposalCreate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ShotChangeProposalResult:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = (
        await session.execute(
            select(Shot).where(Shot.id == shot_id, Shot.project_id == project_id)
        )
    ).scalar_one_or_none()
    if shot is None:
        raise NotFoundError("shot not found")
    existing = (
        await session.execute(
            select(ShotChangeProposal).where(
                ShotChangeProposal.project_id == project_id,
                ShotChangeProposal.idempotency_key == body.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ShotChangeProposalResult(
            proposal=_proposal_read(existing),
            impact={
                "affected_shot_ids": [str(existing.shot_id)],
                "invalidated_node_keys": list(existing.affected_node_keys),
                "reusable_artifact_ids": list(existing.reusable_artifact_ids),
            },
        )
    if shot.version != body.expected_version:
        raise ConflictError(
            "shot change proposal base version conflict",
            details={"expected_version": body.expected_version, "actual_version": shot.version},
        )
    # Validate the replacement payload at the boundary: unknown/invalid fields
    # fail closed here so no malformed proposal is persisted.
    try:
        ShotChangePayload.model_validate(dict(body.replacement_payload))
    except Exception as exc:  # noqa: BLE001 — surface a domain-consistent error
        raise ValidationAppError(
            f"invalid shot change replacement payload: {exc}",
            details={"code": "INVALID_SHOT_CHANGE_PAYLOAD"},
        ) from exc
    proposal = ShotChangeProposal(
        project_id=project_id,
        shot_id=shot.id,
        created_by=user.id,
        idempotency_key=body.idempotency_key,
        summary=body.summary,
        base_shot_version=shot.version,
        replacement_payload=dict(body.replacement_payload),
        affected_node_keys=list(body.affected_node_keys),
        reusable_artifact_ids=list(body.reusable_artifact_ids),
    )
    session.add(proposal)
    await session.commit()
    return ShotChangeProposalResult(
        proposal=_proposal_read(proposal),
        impact={
            "affected_shot_ids": [str(shot.id)],
            "invalidated_node_keys": list(proposal.affected_node_keys),
            "reusable_artifact_ids": list(proposal.reusable_artifact_ids),
        },
    )


@router.get(
    "/projects/{project_id}/shots/{shot_id}/change-proposals",
    response_model=list[ShotChangeProposalRead],
)
async def list_shot_change_proposals(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[ShotChangeProposalRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = (
        await session.execute(
            select(ShotChangeProposal)
            .where(
                ShotChangeProposal.project_id == project_id,
                ShotChangeProposal.shot_id == shot_id,
            )
            .order_by(ShotChangeProposal.created_at.desc())
        )
    ).scalars().all()
    return [_proposal_read(row) for row in rows]


@router.post(
    "/projects/{project_id}/shots/{shot_id}/change-proposals/{proposal_id}/confirm",
    response_model=ShotChangeProposalRead,
)
async def confirm_shot_change_proposal(
    project_id: UUID,
    shot_id: UUID,
    proposal_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ShotChangeProposalRead:
    """Apply a confirmed agent proposal atomically (§19.5).

    User acceptance is the operation that applies the proposal: lock the Shot,
    require the proposal to be ``awaiting_confirmation`` and its base version to
    still match the Shot, validate the persisted replacement payload, compute the
    complete resulting Shot canvas state (current Shot + validated overrides),
    write that exact state to both a new ``source="assistant"`` CanvasRevision
    and the Shot, bump the Shot version, and mark the proposal applied — all in
    one transaction. Confirming an already-applied proposal is idempotent: it
    returns the existing result without creating another revision or bumping the
    version. A stale proposal whose base version no longer matches the Shot fails
    with Conflict and never overwrites newer user edits.
    """
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    proposal = (
        await session.execute(
            select(ShotChangeProposal).where(
                ShotChangeProposal.id == proposal_id,
                ShotChangeProposal.project_id == project_id,
                ShotChangeProposal.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise NotFoundError("shot change proposal not found")
    if proposal.status == "applied":
        # Idempotent retry: no new revision, no version bump.
        return _proposal_read(proposal)
    if proposal.status != "awaiting_confirmation":
        raise ConflictError("shot change proposal is not awaiting confirmation")

    shot = (
        await session.execute(
            select(Shot)
            .where(Shot.id == shot_id, Shot.project_id == project_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if shot is None:
        raise NotFoundError("shot not found")
    if shot.version != proposal.base_shot_version:
        raise ConflictError(
            "shot change proposal base version conflict",
            details={
                "expected_version": proposal.base_shot_version,
                "actual_version": shot.version,
            },
        )

    # Re-validate the persisted payload (defense-in-depth against legacy JSON).
    try:
        payload = ShotChangePayload.model_validate(dict(proposal.replacement_payload))
    except Exception as exc:  # noqa: BLE001 — surface a domain-consistent error
        raise ValidationAppError(
            f"invalid shot change replacement payload: {exc}",
            details={"code": "INVALID_SHOT_CHANGE_PAYLOAD"},
        ) from exc

    # Complete resulting state = current Shot canvas + validated overrides.
    # A proposal is a partial replacement; fields not present keep the current
    # Shot value, and the exact same complete state goes to both the CanvasRevision
    # and the Shot.
    new_visual = (
        payload.visual_description
        if payload.visual_description is not None
        else shot.visual_description
    )
    new_shot_type = payload.shot_type if payload.shot_type is not None else shot.shot_type
    new_camera_move = payload.camera_move if payload.camera_move is not None else shot.camera_move
    new_dialogue = payload.dialogue if payload.dialogue is not None else shot.dialogue
    if payload.duration_seconds is not None:
        new_duration = payload.duration_seconds
    else:
        new_duration = shot.duration_seconds

    latest_revision = (
        await session.execute(
            select(func.max(CanvasRevision.revision_number)).where(
                CanvasRevision.shot_id == shot.id
            )
        )
    ).scalar_one()
    revision = CanvasRevision(
        project_id=project_id,
        shot_id=shot.id,
        revision_number=int(latest_revision or 0) + 1,
        base_shot_version=shot.version,
        visual_description=new_visual,
        shot_type=new_shot_type,
        camera_move=new_camera_move,
        dialogue=new_dialogue,
        duration_seconds=new_duration,
        source="assistant",
        created_by=user.id,
    )
    session.add(revision)
    await session.flush()

    shot.visual_description = new_visual
    shot.shot_type = new_shot_type
    shot.camera_move = new_camera_move
    shot.dialogue = new_dialogue
    shot.duration_seconds = new_duration
    shot.version += 1

    proposal.status = "applied"
    proposal.confirmed_revision_id = revision.id
    proposal.confirmed_at = datetime.now(UTC)
    await session.commit()
    return _proposal_read(proposal)

@router.patch(
    "/projects/{project_id}/shots/{shot_id}/canvas",
    response_model=ShotCanvasUpdateResponse,
)
async def update_shot_canvas(
    project_id: UUID,
    shot_id: UUID,
    body: ShotCanvasUpdateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ShotCanvasUpdateResponse:
    """Persist an immutable CanvasRevision and advance the Shot version."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = (
        await session.execute(
            select(Shot)
            .where(Shot.id == shot_id, Shot.project_id == project_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if shot is None:
        raise NotFoundError("shot not found")
    if shot.version != body.expected_version:
        raise ConflictError(
            "shot canvas version conflict",
            details={"expected_version": body.expected_version, "actual_version": shot.version},
        )
    latest_revision = (
        await session.execute(
            select(func.max(CanvasRevision.revision_number)).where(
                CanvasRevision.shot_id == shot.id
            )
        )
    ).scalar_one()
    revision = CanvasRevision(
        project_id=project_id,
        shot_id=shot.id,
        revision_number=int(latest_revision or 0) + 1,
        base_shot_version=shot.version,
        visual_description=body.visual_description,
        shot_type=body.shot_type,
        camera_move=body.camera_move,
        dialogue=body.dialogue,
        duration_seconds=body.duration_seconds or shot.duration_seconds,
        source=body.source,
        created_by=user.id,
    )
    shot.visual_description = body.visual_description
    shot.shot_type = body.shot_type
    shot.camera_move = body.camera_move
    shot.dialogue = body.dialogue
    if body.duration_seconds is not None:
        shot.duration_seconds = body.duration_seconds
    shot.version += 1
    session.add(revision)
    await session.commit()
    return ShotCanvasUpdateResponse(
        shot=_shot_read(shot), revision_id=revision.id, revision_number=revision.revision_number
    )



@router.get(
    "/projects/{project_id}/shots/{shot_id}/canvas-revisions",
    response_model=list[CanvasRevisionRead],
)
async def list_shot_canvas_revisions(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[CanvasRevisionRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot_exists = (
        await session.execute(
            select(Shot.id).where(Shot.id == shot_id, Shot.project_id == project_id)
        )
    ).scalar_one_or_none()
    if shot_exists is None:
        raise NotFoundError("shot not found")
    rows = (
        await session.execute(
            select(CanvasRevision)
            .where(CanvasRevision.project_id == project_id, CanvasRevision.shot_id == shot_id)
            .order_by(CanvasRevision.revision_number.desc())
        )
    ).scalars().all()
    return [
        CanvasRevisionRead(
            id=row.id,
            revision_number=row.revision_number,
            base_shot_version=row.base_shot_version,
            visual_description=row.visual_description,
            shot_type=row.shot_type,
            camera_move=row.camera_move,
            dialogue=row.dialogue,
            duration_seconds=row.duration_seconds,
            source=row.source,
            created_at=row.created_at,
        )
        for row in rows
    ]

@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
async def list_project_shots(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[ShotRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = list(
        (
            await session.execute(
                select(Shot)
                .where(Shot.project_id == project_id)
                .order_by(Shot.sort_order, Shot.shot_number)
            )
        )
        .scalars()
        .all()
    )
    return [_shot_read(row) for row in rows]
