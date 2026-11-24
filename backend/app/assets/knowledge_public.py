"""The shared knowledge projection. Private research models never supply relationship IDs."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.knowledge_models import KnowledgeEntry, KnowledgeRevision
from app.assets.research_bodies import (
    CulturalClueBody,
    NamedBody,
    ResearchBodyBase,
    SummaryBody,
    TimelineItem,
    TimePoint,
)
from app.assets.source_use_models import USE_PURPOSES
from app.shared.errors import ValidationAppError


class _Related(ResearchBodyBase):
    related_entry_ids: list[UUID] = Field(default_factory=list, max_length=100)


class _Summary(SummaryBody, _Related):
    pass


class _Named(NamedBody, _Related):
    pass


class _Event(_Related):
    description: str = Field(min_length=1, max_length=20_000)
    time: TimePoint | None = None
    participant_entry_ids: list[UUID] = Field(default_factory=list, max_length=100)
    place_entry_ids: list[UUID] = Field(default_factory=list, max_length=100)


class _TimelineItem(TimelineItem):
    event_entry_id: UUID | None = None


class _Timeline(_Related):
    items: list[_TimelineItem] = Field(min_length=1, max_length=200)


class _Clue(CulturalClueBody, _Related):
    pass


_BODIES: dict[str, type[ResearchBodyBase]] = {
    "summary": _Summary,
    "person": _Named,
    "place": _Named,
    "event": _Event,
    "timeline": _Timeline,
    "cultural_clue": _Clue,
}
_RELATIONS = {"related_entry_ids", "participant_entry_ids", "place_entry_ids", "event_entry_id"}
_PRIVATE = re.compile(
    r"(?i)(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])"
    r"|(?:projects|workspaces|provider-references|artifacts|objects|obj|private|secrets|tokens)/"
    r"|\b(?:s3|minio|file|data)\s*:|(?<![a-z0-9+.-])[a-z]:[\\/]|\\\\"
    r"|\b(?:bearer\s+[a-z0-9._~+/-]{8,}|(?:sk-|ghp_|github_pat_|glpat-|xox[baprs]-)[a-z0-9_-]{8,}"
    r"|AKIA[A-Z0-9]{16}|authorization\s*:\s*basic\s+|-----BEGIN [^-]*PRIVATE KEY)"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|(?:api[_-]?key|password|credential|secret|signature|token|object[_-]?key)\s*[\x22\x27]?\s*[=:])"
)
_WEB = re.compile(r"https?://[^\s<>\x22\x27]+", re.I)
_QUERY_FIELD = re.compile(
    r"(?:id|page|p|year|volume|issue|chapter|section|lang|isbn|doi|title|author|q)",
    re.I,
)
_PUBLIC_SELECTOR = re.compile(r"[\w.~-]{1,80}", re.UNICODE)


def _opaque_selector(value: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", value):
        return False
    # Retain readable catalogue slugs with a year or numbered volume.
    if re.fullmatch(r"(?:[a-z]{1,20}|\d{1,4})(?:[-_](?:[a-z]{1,20}|\d{1,4})){2,}", value):
        return False
    return len(value) >= 40 or any(c.isdigit() or c.isupper() for c in value)


def _decoded(value: str) -> str:
    # Inspect the actual characters, including nested escaping. Ambiguous encodings fail closed.
    value = unicodedata.normalize("NFKC", value)
    for _ in range(4):
        decoded = unquote(value, errors="strict")
        if decoded == value:
            return value
        value = unicodedata.normalize("NFKC", decoded)
    raise ValueError("ambiguous encoding")


def _public_url(value: str) -> bool:
    try:
        decoded = _decoded(value)
        if (
            any(c.isspace() for c in value)
            or any(ord(c) < 32 for c in decoded)
            or "\\" in decoded
            or _PRIVATE.search(decoded)
            or re.search(r"%(?![A-Fa-f0-9]{2})", value)
        ):
            return False
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme != "https" or url.username is not None or url.password is not None:
            return False
        if not host or "%" in url.netloc or url.port == 0:
            return False
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            labels = host.encode("idna").decode().split(".")
            if (
                len(labels) < 2
                or labels[-1] in {"local", "localhost", "internal", "lan"}
                or not re.fullmatch(r"[a-z][a-z0-9-]+", labels[-1])
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", s) for s in labels)
            ):
                return False
        else:
            if not addr.is_global:
                return False
        path = _decoded(url.path)
        if any(c in path for c in "?#;="):
            return False
        if re.search(r"(?i)(?:^|/)(?:api|share|signed|download-token|auth)(?:/|$)", path):
            return False
        if any(_opaque_selector(s) for s in path.split("/")):
            return False
        if url.fragment and (
            not _PUBLIC_SELECTOR.fullmatch(_decoded(url.fragment))
            or _opaque_selector(_decoded(url.fragment))
        ):
            return False
        return all(
            _QUERY_FIELD.fullmatch(k) and _PUBLIC_SELECTOR.fullmatch(v) and not _opaque_selector(v)
            for k, v in parse_qsl(url.query, strict_parsing=True, keep_blank_values=True)
        )
    except (UnicodeError, ValueError):
        return False


def public_text(value: str) -> bool:
    try:
        inspected = _decoded(value)
    except (UnicodeError, ValueError):
        return False
    if _PRIVATE.search(inspected) or any(ord(c) < 32 and c not in "\n\r\t" for c in inspected):
        return False
    return all(
        _public_url(link.group().rstrip(".,，。；;）)"))
        for text in (value, inspected)
        for link in _WEB.finditer(text)
    )


class SharedNote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=240)
    public_url: str | None = Field(default=None, max_length=2000)
    locator_note: str | None = Field(default=None, max_length=1000)


def canonical_note(raw: object) -> dict[str, object]:
    try:
        note = SharedNote.model_validate(raw)
    except ValidationError:
        raise ValidationAppError(
            "来源注记格式无效", details={"code": "KNOWLEDGE_NOTE_INVALID"}
        ) from None
    if note.public_url is not None and not _public_url(note.public_url):
        raise ValidationAppError(
            "请使用公开文献的 HTTPS 引用地址", details={"code": "KNOWLEDGE_NOTE_URL_INVALID"}
        )
    if not public_text(note.label) or not public_text(note.locator_note or ""):
        raise ValidationAppError(
            "来源注记含私有标识或凭据", details={"code": "KNOWLEDGE_NOTE_INVALID"}
        )
    return note.model_dump()


def _check_text(value: object) -> bool:
    if isinstance(value, dict):
        return all(_check_text(v) for k, v in value.items() if k not in _RELATIONS)
    if isinstance(value, list):
        return all(_check_text(v) for v in value)
    return not isinstance(value, str) or public_text(value)


def canonical_body(kind: str, raw: object) -> dict[str, object]:
    try:
        parsed = _BODIES[kind].model_validate(raw)
    except (KeyError, ValidationError):
        raise ValidationAppError(
            "知识正文含不支持的字段或版本", details={"code": "KNOWLEDGE_BODY_INVALID"}
        ) from None
    body = parsed.model_dump(mode="json")
    # Omit empty optional relations. Keep the content and hash of ordinary unlinked records stable.
    for fields in _relation_fields(body):
        for key in _RELATIONS & fields.keys():
            if not fields[key]:
                del fields[key]
    if not _check_text(body):
        raise ValidationAppError(
            "知识正文含私有标识或凭据", details={"code": "KNOWLEDGE_BODY_INVALID"}
        )
    return body


def _relation_fields(body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield body
    yield from body.get("items", [])


def _relation_ids(body: dict[str, Any]) -> set[UUID]:
    return {
        UUID(v)
        for fields in _relation_fields(body)
        for k in fields.keys() & _RELATIONS
        for v in (fields[k] if isinstance(fields[k], list) else [fields[k]])
    }


async def _published_ids(db: AsyncSession, owner_id: UUID, ids: set[UUID]) -> set[UUID]:
    if not ids:
        return set()
    query = (
        select(KnowledgeEntry.id)
        .where(
            KnowledgeEntry.owner_user_id == owner_id,
            KnowledgeEntry.id.in_(ids),
            KnowledgeEntry.publication_status == "published",
            KnowledgeEntry.current_revision_id.is_not(None),
        )
        .order_by(KnowledgeEntry.id)
    )
    return set(await db.scalars(query))


async def lock_write_scope(
    db: AsyncSession,
    owner_id: UUID,
    body: dict[str, object],
    entry_id: UUID | None = None,
) -> None:
    related = _relation_ids(body)
    ids = related | ({entry_id} if entry_id else set())
    if not ids:
        return
    entries = list(
        await db.scalars(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.owner_user_id == owner_id,
                KnowledgeEntry.id.in_(ids),
            )
            .order_by(KnowledgeEntry.id)
            .with_for_update(read=entry_id is None)
            .execution_options(populate_existing=True)
        )
    )
    published = {
        entry.id
        for entry in entries
        if entry.publication_status == "published" and entry.current_revision_id is not None
    }
    if not related <= published:
        raise ValidationAppError(
            "关联必须指向本人已发布的知识条目", details={"code": "KNOWLEDGE_RELATION_UNAVAILABLE"}
        )


class KnowledgeRevisionRead(BaseModel):
    id: UUID
    entry_id: UUID
    number: int
    title: str
    body: dict[str, object]
    allowed_uses: list[str]
    public_source_notes: list[dict[str, object]]
    content_hash: str
    operation: str
    publication_status: str
    result_entry_version: int
    created_at: datetime
    shared_content_state: Literal["complete", "filtered", "unavailable"]

    def matches(self, query: str) -> bool:
        def words(value: object) -> Iterator[str]:
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for child in value:
                    yield from words(child)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key not in _RELATIONS:
                        yield from words(child)

        visible = " ".join(" ".join((self.title, *words(self.body))).split()).casefold()
        return query.casefold() in visible


async def shared_revisions(
    db: AsyncSession, owner_id: UUID, kind: str, rows: list[KnowledgeRevision]
) -> list[KnowledgeRevisionRead]:
    views: list[KnowledgeRevisionRead] = []
    ids: set[UUID] = set()
    for row in rows:
        state: Literal["complete", "filtered", "unavailable"] = "complete"
        raw = dict(row.body) if isinstance(row.body, dict) else {}
        for key in (
            "related_person_ids",
            "related_place_ids",
            "related_result_ids",
            "participant_result_ids",
            "place_result_ids",
        ):
            if raw.pop(key, None):
                state = "filtered"
        raw_items = raw.get("items")
        if isinstance(raw_items, list):
            timeline = []
            for item in raw_items:
                if isinstance(item, dict) and "event_result_id" in item:
                    item = dict(item)
                    if item.pop("event_result_id"):
                        state = "filtered"
                timeline.append(item)
            raw["items"] = timeline
        try:
            body = canonical_body(kind, raw)
        except ValidationAppError:
            body = {}
            state = "unavailable"
        ids.update(_relation_ids(body))
        title = row.title
        if not public_text(title):
            title = "内容待核对"
            state = "unavailable"
        notes = []
        if not isinstance(row.public_source_notes, list) and state == "complete":
            state = "filtered"
        for note in row.public_source_notes if isinstance(row.public_source_notes, list) else []:
            try:
                notes.append(canonical_note(note))
            except ValidationAppError:
                if state == "complete":
                    state = "filtered"
        views.append(
            KnowledgeRevisionRead(
                id=row.id,
                entry_id=row.entry_id,
                number=row.number,
                title=title,
                body=body,
                allowed_uses=[v for v in row.allowed_uses if v in USE_PURPOSES],
                public_source_notes=notes,
                content_hash=row.content_hash,
                operation=row.operation,
                publication_status=row.publication_status,
                result_entry_version=row.result_entry_version,
                created_at=row.created_at,
                shared_content_state=state,
            )
        )
    visible = {str(v) for v in await _published_ids(db, owner_id, ids)}
    for view in views:
        for fields in _relation_fields(view.body):
            for key in fields.keys() & _RELATIONS:
                value = fields[key]
                remaining = (
                    [v for v in value if v in visible]
                    if isinstance(value, list)
                    else value
                    if value in visible
                    else None
                )
                if remaining != value:
                    if remaining:
                        fields[key] = remaining
                    else:
                        del fields[key]
                    if view.shared_content_state == "complete":
                        view.shared_content_state = "filtered"
    return views
