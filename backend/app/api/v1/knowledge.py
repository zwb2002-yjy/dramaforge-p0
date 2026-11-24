"""Owner-scoped knowledge entries, explicit drafts/publication and withdrawal (I4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.knowledge import (
    KnowledgeMutationReceipt,
    KnowledgeService,
    PublicSourceNote,
    SourceLinkInput,
)
from app.assets.knowledge_models import KnowledgeEntry
from app.assets.knowledge_public import KnowledgeRevisionRead
from app.assets.knowledge_references import KnowledgeReferenceService, ReferenceRead
from app.assets.research_bodies import summary_text

router = APIRouter(tags=["knowledge"], dependencies=[Depends(require_selected_workspace)])


class SourceNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=240)
    public_url: str | None = Field(default=None, max_length=2_000)
    locator_note: str | None = Field(default=None, max_length=1_000)


class SourceLinkWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    research_revision_id: UUID


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    workspace_id: UUID
    kind: str = Field(max_length=24)
    operation: str = Field(max_length=16)
    title: str = Field(min_length=1, max_length=240)
    body: dict[str, object]
    allowed_uses: list[str] = Field(default_factory=list, max_length=20)
    public_source_notes: list[SourceNoteInput] = Field(default_factory=list, max_length=20)
    source_links: list[SourceLinkWrite] = Field(default_factory=list, max_length=20)


class KnowledgeAppend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    operation: str = Field(max_length=16)
    title: str = Field(min_length=1, max_length=240)
    body: dict[str, object]
    allowed_uses: list[str] = Field(default_factory=list, max_length=20)
    public_source_notes: list[SourceNoteInput] = Field(default_factory=list, max_length=20)
    source_links: list[SourceLinkWrite] = Field(default_factory=list, max_length=20)


class KnowledgeWithdraw(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)


class KnowledgeReceiptRead(BaseModel):
    entry_id: UUID
    revision_id: UUID
    result_entry_version: int
    publication_status: str
    content_hash: str


class KnowledgeEntryRead(BaseModel):
    shared_content_state: Literal["complete", "filtered", "unavailable"]
    id: UUID
    kind: str
    version: int
    publication_status: str
    current_revision_id: UUID | None
    title: str | None
    summary: str | None
    allowed_uses: list[str]
    updated_at: datetime | None


class KnowledgeEntryPage(BaseModel):
    items: list[KnowledgeEntryRead]
    total: int
    next_offset: int | None


class KnowledgeRevisionPage(BaseModel):
    items: list[KnowledgeRevisionRead]
    total: int
    next_offset: int | None


def _receipt(receipt: KnowledgeMutationReceipt) -> KnowledgeReceiptRead:
    return KnowledgeReceiptRead(
        entry_id=receipt.entry_id,
        revision_id=receipt.revision_id,
        result_entry_version=receipt.result_entry_version,
        publication_status=receipt.publication_status,
        content_hash=receipt.content_hash,
    )


def _entry_read(entry: KnowledgeEntry, current: KnowledgeRevisionRead | None) -> KnowledgeEntryRead:
    return KnowledgeEntryRead(
        shared_content_state=current.shared_content_state if current else "unavailable",
        id=entry.id,
        kind=entry.kind,
        version=entry.version,
        publication_status=entry.publication_status,
        current_revision_id=entry.current_revision_id,
        title=current.title if current is not None else None,
        summary=summary_text(entry.kind, current.body) if current is not None else None,
        allowed_uses=[str(value) for value in current.allowed_uses] if current is not None else [],
        updated_at=current.created_at if current is not None else None,
    )


def _notes(values: list[SourceNoteInput]) -> list[PublicSourceNote]:
    return [
        PublicSourceNote(
            label=value.label, public_url=value.public_url, locator_note=value.locator_note
        )
        for value in values
    ]


def _links(values: list[SourceLinkWrite]) -> list[SourceLinkInput]:
    return [
        SourceLinkInput(
            project_id=value.project_id,
            research_revision_id=value.research_revision_id,
        )
        for value in values
    ]


async def _current(
    service: KnowledgeService, entry: KnowledgeEntry
) -> KnowledgeRevisionRead | None:
    if entry.current_revision_id is None:
        return None
    return await service.read_revision(entry.current_revision_id)


@router.post("/knowledge/entries", response_model=KnowledgeReceiptRead, status_code=201)
async def create_knowledge_entry(
    body: KnowledgeCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> KnowledgeReceiptRead:
    service = KnowledgeService(session, actor=user)
    receipt = await service.create_entry(
        workspace_id=body.workspace_id,
        kind=body.kind,
        title=body.title,
        body=body.body,
        allowed_uses=body.allowed_uses,
        public_source_notes=_notes(body.public_source_notes),
        source_links=_links(body.source_links),
        operation=body.operation,
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.get("/knowledge/entries", response_model=KnowledgeEntryPage)
async def list_knowledge_entries(
    user: CurrentUser,
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=24),
    status: str = Query(default="published", max_length=16),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeEntryPage:
    service = KnowledgeService(session, actor=user)
    rows, total = await service.list_entries(
        kind=kind, status=status, query=q, limit=limit, offset=offset
    )
    items: list[KnowledgeEntryRead] = []
    for entry in rows:
        items.append(_entry_read(entry, await _current(service, entry)))
    return KnowledgeEntryPage(
        items=items,
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get("/knowledge/entries/{entry_id}", response_model=KnowledgeEntryRead)
async def read_knowledge_entry(
    entry_id: UUID, user: CurrentUser, session: SessionDep
) -> KnowledgeEntryRead:
    service = KnowledgeService(session, actor=user)
    entry = await service.read_entry(entry_id)
    return _entry_read(entry, await _current(service, entry))


@router.get("/knowledge/entries/{entry_id}/revisions", response_model=KnowledgeRevisionPage)
async def list_knowledge_revisions(
    entry_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeRevisionPage:
    service = KnowledgeService(session, actor=user)
    rows, total = await service.list_revisions(entry_id, limit=limit, offset=offset)
    return KnowledgeRevisionPage(
        items=rows,
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.post(
    "/knowledge/entries/{entry_id}/revisions",
    response_model=KnowledgeReceiptRead,
    status_code=201,
)
async def append_knowledge_revision(
    entry_id: UUID,
    body: KnowledgeAppend,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> KnowledgeReceiptRead:
    service = KnowledgeService(session, actor=user)
    receipt = await service.append_revision(
        entry_id,
        expected_version=body.expected_version,
        title=body.title,
        body=body.body,
        allowed_uses=body.allowed_uses,
        public_source_notes=_notes(body.public_source_notes),
        source_links=_links(body.source_links),
        operation=body.operation,
        request_key=body.request_key,
    )
    await session.commit()
    return _receipt(receipt)


@router.post(
    "/knowledge/entries/{entry_id}/withdraw",
    response_model=KnowledgeReceiptRead,
    status_code=201,
)
async def withdraw_knowledge_entry(
    entry_id: UUID,
    body: KnowledgeWithdraw,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> KnowledgeReceiptRead:
    service = KnowledgeService(session, actor=user)
    receipt = await service.withdraw(
        entry_id, expected_version=body.expected_version, request_key=body.request_key
    )
    await session.commit()
    return _receipt(receipt)


class ReferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_entry_id: UUID
    knowledge_revision_id: UUID
    allowed_use: str = Field(max_length=40)


class ReferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    attached: bool


class ReferenceReadModel(BaseModel):
    id: UUID
    project_id: UUID
    knowledge_entry_id: UUID
    knowledge_revision_id: UUID
    allowed_use: str
    version: int
    detached_at: datetime | None
    availability: str


class ReferencePage(BaseModel):
    items: list[ReferenceReadModel]
    total: int
    next_offset: int | None


def _reference_read(reference: ReferenceRead) -> ReferenceReadModel:
    return ReferenceReadModel(
        id=reference.id,
        project_id=reference.project_id,
        knowledge_entry_id=reference.knowledge_entry_id,
        knowledge_revision_id=reference.knowledge_revision_id,
        allowed_use=reference.allowed_use,
        version=reference.version,
        detached_at=reference.detached_at,
        availability=reference.availability,
    )


@router.get("/projects/{project_id}/knowledge-references", response_model=ReferencePage)
async def list_knowledge_references(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    active: bool = True,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReferencePage:
    service = KnowledgeReferenceService(session, actor=user, project_id=project_id)
    rows, total = await service.list(active=active, limit=limit, offset=offset)
    return ReferencePage(
        items=[_reference_read(row) for row in rows],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.post(
    "/projects/{project_id}/knowledge-references",
    response_model=ReferenceReadModel,
    status_code=201,
)
async def create_knowledge_reference(
    project_id: UUID,
    body: ReferenceWrite,
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    _: CsrfDep,
) -> ReferenceReadModel:
    service = KnowledgeReferenceService(session, actor=user, project_id=project_id)
    reference, created = await service.create(
        knowledge_entry_id=body.knowledge_entry_id,
        knowledge_revision_id=body.knowledge_revision_id,
        allowed_use=body.allowed_use,
    )
    await session.commit()
    if not created:
        response.status_code = 200
    return _reference_read(reference)


@router.patch(
    "/projects/{project_id}/knowledge-references/{reference_id}",
    response_model=ReferenceReadModel,
)
async def patch_knowledge_reference(
    project_id: UUID,
    reference_id: UUID,
    body: ReferencePatch,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ReferenceReadModel:
    service = KnowledgeReferenceService(session, actor=user, project_id=project_id)
    reference = await service.patch(
        reference_id, expected_version=body.expected_version, attached=body.attached
    )
    await session.commit()
    return _reference_read(reference)
