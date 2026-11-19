"""Source-use declarations: per-file-revision and per-artifact GET/PUT.

The declaration is a right statement, never an egress permission: the project
egress policy is checked separately at every real send. Reads without a subject
report version 0 / ``unreviewed`` and never create a row; writes with an expected
version are CAS-checked after the request-key replay check.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.source_use import SourceUseService
from app.execution.models import Artifact
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(tags=["source-use"], dependencies=[Depends(require_selected_workspace)])

UsePurpose = Literal["research", "creation", "library_reference", "external_processing", "export"]
SourceUseState = Literal["unreviewed", "declared", "revoked"]


class SourceUseRead(BaseModel):
    subject_id: UUID | None
    version: int
    current_revision_id: UUID | None
    state: SourceUseState
    allowed_uses: list[str]
    statement: str
    evidence_note: str


class SourceUseWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=0, strict=True)
    state: Literal["declared", "revoked"]
    allowed_uses: list[UsePurpose] = Field(default_factory=list, max_length=20)
    statement: str = Field(default="", max_length=4000)
    evidence_note: str = Field(default="", max_length=4000)


class SourceUseReceipt(BaseModel):
    subject_id: UUID
    revision_id: UUID
    result_version: int
    state: SourceUseState
    content_hash: str


class ImpactItem(BaseModel):
    kind: str
    id: str
    usage: str
    status: str


class SourceUseImpact(BaseModel):
    items: list[ImpactItem]
    next_cursor: str | None


async def _scope(
    project_id: UUID, user: User, session: SessionDep,
) -> tuple[Project, SourceUseService]:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return project, SourceUseService(session, actor=user, project=project)


async def _artifact(session: SessionDep, project: Project, artifact_id: UUID) -> Artifact:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise NotFoundError("artifact not found")
    return artifact


async def _read(
    session: SessionDep, service: SourceUseService, *,
    file_revision_id: UUID | None = None, artifact_id: UUID | None = None,
) -> SourceUseRead:
    subject = await service.find_subject(
        file_revision_id=file_revision_id, artifact_id=artifact_id,
    )
    if subject is None:
        return SourceUseRead(
            subject_id=None, version=0, current_revision_id=None, state="unreviewed",
            allowed_uses=[], statement="", evidence_note="",
        )
    revision = await service.current(subject.id)
    if revision is None:
        return SourceUseRead(
            subject_id=subject.id, version=subject.version, current_revision_id=None,
            state="unreviewed", allowed_uses=[], statement="", evidence_note="",
        )
    return SourceUseRead(
        subject_id=subject.id,
        version=subject.version,
        current_revision_id=revision.id,
        state=cast(SourceUseState, revision.state),
        allowed_uses=[str(value) for value in revision.allowed_uses],
        statement=revision.statement,
        evidence_note=revision.evidence_note,
    )


async def _write(
    session: SessionDep, service: SourceUseService, body: SourceUseWrite, *,
    file_revision_id: UUID | None = None, artifact_id: UUID | None = None,
) -> SourceUseReceipt:
    if body.state == "declared" and (not body.statement.strip() or not body.allowed_uses):
        raise ValidationAppError(
            "声明用途必须写明声明且至少选择一个用途",
            details={"code": "SOURCE_USE_DECLARATION_INCOMPLETE"},
        )
    if body.state == "revoked" and body.allowed_uses:
        raise ValidationAppError(
            "撤回声明不能携带用途",
            details={"code": "SOURCE_USE_REVOKED_WITH_USES"},
        )
    revision = await service.declare(
        file_revision_id=file_revision_id,
        artifact_id=artifact_id,
        allowed_uses=list(body.allowed_uses),
        statement=body.statement,
        evidence_note=body.evidence_note,
        request_key=body.request_key,
        state=body.state,
        expected_version=body.expected_version,
    )
    await session.commit()
    return SourceUseReceipt(
        subject_id=revision.subject_id,
        revision_id=revision.id,
        result_version=revision.result_version,
        state=cast(SourceUseState, revision.state),
        content_hash=revision.content_hash,
    )


@router.get(
    "/projects/{project_id}/file-revisions/{revision_id}/source-use",
    response_model=SourceUseRead,
)
async def read_file_source_use(
    project_id: UUID, revision_id: UUID, user: CurrentUser, session: SessionDep,
) -> SourceUseRead:
    _project, service = await _scope(project_id, user, session)
    return await _read(session, service, file_revision_id=revision_id)


@router.put(
    "/projects/{project_id}/file-revisions/{revision_id}/source-use",
    response_model=SourceUseReceipt,
)
async def write_file_source_use(
    project_id: UUID, revision_id: UUID, body: SourceUseWrite,
    user: CurrentUser, session: SessionDep, _csrf: CsrfDep,
) -> SourceUseReceipt:
    _project, service = await _scope(project_id, user, session)
    return await _write(session, service, body, file_revision_id=revision_id)


@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/source-use",
    response_model=SourceUseRead,
)
async def read_artifact_source_use(
    project_id: UUID, artifact_id: UUID, user: CurrentUser, session: SessionDep,
) -> SourceUseRead:
    project, service = await _scope(project_id, user, session)
    await _artifact(session, project, artifact_id)
    return await _read(session, service, artifact_id=artifact_id)


@router.put(
    "/projects/{project_id}/artifacts/{artifact_id}/source-use",
    response_model=SourceUseReceipt,
)
async def write_artifact_source_use(
    project_id: UUID, artifact_id: UUID, body: SourceUseWrite,
    user: CurrentUser, session: SessionDep, _csrf: CsrfDep,
) -> SourceUseReceipt:
    project, service = await _scope(project_id, user, session)
    await _artifact(session, project, artifact_id)
    return await _write(session, service, body, artifact_id=artifact_id)


@router.get(
    "/projects/{project_id}/source-use-subjects/{subject_id}/impact",
    response_model=SourceUseImpact,
)
async def read_source_use_impact(
    project_id: UUID,
    subject_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = 50,
    cursor: str | None = None,
) -> SourceUseImpact:
    _project, service = await _scope(project_id, user, session)
    uses, next_cursor = await service.impact(
        subject_id=subject_id, limit=limit, cursor=cursor,
    )
    items: list[ImpactItem] = []
    for use in uses:
        artifact = await session.get(Artifact, use.artifact_id)
        if artifact is None:
            status = "missing"
        elif artifact.deleted_at is not None:
            status = "like_deleted"
        else:
            status = str(artifact.storage_state)
        items.append(
            ImpactItem(
                kind="artifact", id=str(use.artifact_id), usage=use.input_role, status=status,
            )
        )
    return SourceUseImpact(items=items, next_cursor=next_cursor)


__all__ = ["router"]
