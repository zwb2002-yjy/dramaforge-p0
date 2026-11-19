"""Project-scoped originals and versioned local extraction; no creative writes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.source_blocks import parse_pdf_with_blocks
from app.assets.source_models import SourceExtraction, SourceFragment
from app.assets.source_parser import (
    MAX_SOURCE_BYTES,
    ParsedSource,
    SourceParseError,
    parse_source,
    processor_profile_revision,
)
from app.events.models import EventLog
from app.events.service import EventService
from app.shared.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore

EXTRACTION_EVENT = "project_file.extraction_requested"


class SourceAcceptanceError(AppError):
    """Stable 409 for retry/reparse acceptance conflicts (never a silent rewrite)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


@dataclass(frozen=True)
class ExtractionAcceptance:
    """Durable receipt of one accepted attempt; the worker owns the actual work."""

    file_revision_id: UUID
    accepted_attempt: int
    event_id: UUID
    processor_profile_revision: str
    action: str


def current_processor_profile() -> str:
    return processor_profile_revision()


def _acceptance_hash(
    *,
    revision_id: UUID,
    action: str,
    request_key: str,
    expected_file_version: int,
    expected_attempt: int,
    expected_extraction_id: UUID | None,
    processor_profile_revision: str,
) -> str:
    payload = [
        str(revision_id),
        action,
        request_key,
        expected_file_version,
        expected_attempt,
        str(expected_extraction_id) if expected_extraction_id else None,
        processor_profile_revision,
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _fragment_content_hash(parsed: ParsedSource) -> str:
    """Stable identity of the extracted content, independent of database ids."""
    payload = [
        [
            fragment.ordinal,
            fragment.locator_kind,
            fragment.locator,
            fragment.text,
            fragment.extraction_method,
            fragment.processor_ref,
        ]
        for fragment in parsed.fragments
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()



class ProjectFileService:
    """Caller owns commit; every public operation rechecks authenticated ownership."""

    def __init__(
        self, session: AsyncSession, *, store: ObjectStore, actor: User, project_id: UUID
    ) -> None:
        self.session = session
        self.store = store
        self.actor = actor
        self.project_id = project_id

    async def _authorize(self) -> None:
        await ProjectService(self.session).get_project_for_owner(
            project_id=self.project_id,
            actor=self.actor,
        )

    async def _file(self, file_id: UUID, *, lock: bool = False) -> ProjectFile:
        query = (
            select(ProjectFile)
            .where(
                ProjectFile.id == file_id,
                ProjectFile.project_id == self.project_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise NotFoundError("project file not found")
        return row

    async def list_files(self, *, limit: int = 50, offset: int = 0) -> list[ProjectFile]:
        await self._authorize()
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid source page")
        return list(
            await self.session.scalars(
                select(ProjectFile)
                .where(
                    ProjectFile.project_id == self.project_id,
                    ProjectFile.detached_at.is_(None),
                )
                .order_by(ProjectFile.created_at, ProjectFile.id)
                .limit(limit)
                .offset(offset)
            )
        )

    async def read_revision(self, revision_id: UUID) -> tuple[ProjectFile, ProjectFileRevision]:
        await self._authorize()
        row = await self.session.scalar(
            select(ProjectFileRevision).where(
                ProjectFileRevision.id == revision_id,
                ProjectFileRevision.project_id == self.project_id,
            )
        )
        if row is None:
            raise NotFoundError("source revision not found")
        return await self._file(row.file_id), row

    async def read_current(self, file_id: UUID) -> tuple[ProjectFile, ProjectFileRevision]:
        await self._authorize()
        item = await self._file(file_id)
        revision = await self.session.scalar(
            select(ProjectFileRevision).where(
                ProjectFileRevision.project_id == self.project_id,
                ProjectFileRevision.file_id == file_id,
                ProjectFileRevision.number == item.content_version,
            )
        )
        if revision is None:
            raise NotFoundError("source revision not found")
        return item, revision

    async def original(self, revision_id: UUID) -> tuple[ProjectFileRevision, bytes]:
        item, revision = await self.read_revision(revision_id)
        if item.detached_at:
            raise NotFoundError("source is no longer available")
        return revision, await self._original_bytes(revision)

    async def _original_bytes(self, revision: ProjectFileRevision) -> bytes:
        if await self.store.get_size(object_key=revision.object_key) != revision.byte_size:
            raise ValidationAppError("Source storage integrity mismatch")
        data = b""
        if revision.byte_size:
            data = await self.store.get_range(
                object_key=revision.object_key,
                offset=0,
                length=revision.byte_size,
            )
        if (
            len(data) != revision.byte_size
            or hashlib.sha256(data).hexdigest() != revision.content_hash
        ):
            raise ValidationAppError("Source storage integrity mismatch")
        return data

    async def upload(
        self,
        *,
        filename: str,
        data: bytes,
        mime_type: str,
        request_key: str,
        file_id: UUID | None = None,
        expected_version: int | None = None,
    ) -> ProjectFileRevision:
        await self._authorize()
        if (
            not filename.strip()
            or len(filename) > 260
            or any(c in filename for c in "\x00/\\")
            or not 1 <= len(request_key) <= 160
            or not 1 <= len(mime_type) <= 120
            or len(data) > MAX_SOURCE_BYTES
        ):
            raise ValidationAppError("Invalid source upload metadata or size")
        if (file_id is None) != (expected_version is None):
            raise ValidationAppError("File updates require an expected version")
        content_hash = hashlib.sha256(data).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps(
                [filename, content_hash, mime_type, str(file_id), expected_version],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        async def replay() -> ProjectFileRevision | None:
            previous = await self.session.scalar(
                select(ProjectFileRevision).where(
                    ProjectFileRevision.project_id == self.project_id,
                    ProjectFileRevision.request_key == request_key,
                )
            )
            if previous and previous.request_hash != request_hash:
                raise ConflictError("Upload request key already used for different content")
            return previous

        if previous := await replay():
            return previous
        # Reject foreign/unlinked/stale targets before storage writes. The lock
        # below repeats this check after the I/O; no row lock spans storage I/O.
        if file_id is not None:
            existing = await self._file(file_id)
            if existing.detached_at or existing.version != expected_version:
                raise ConflictError("Source association changed")
        object_key = f"projects/{self.project_id}/sources/{content_hash}"
        stored = await self.store.put_bytes(
            object_key=object_key,
            data=data,
            mime_type="application/octet-stream",
        )
        if (
            stored.content_hash != content_hash
            or stored.byte_size != len(data)
            or stored.object_key != object_key
        ):
            raise ValidationAppError("Source storage integrity mismatch")
        # Serialize upload admission, not parsing or storage. Concurrent retries
        # return the same revision and enqueue exactly one extraction event.
        await self.session.scalar(
            select(Project)
            .where(
                Project.id == self.project_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        await self._authorize()
        if previous := await replay():
            return previous
        if file_id is None:
            item = ProjectFile(
                id=uuid4(),
                project_id=self.project_id,
                filename=filename,
                content_version=1,
                version=1,
            )
            self.session.add(item)
            await self.session.flush()
        else:
            item = await self._file(file_id, lock=True)
            if item.detached_at or item.version != expected_version:
                raise ConflictError("Source association changed")
            item.content_version += 1
            item.version += 1
            item.filename = filename
        revision = ProjectFileRevision(
            id=uuid4(),
            project_id=self.project_id,
            file_id=item.id,
            number=item.content_version,
            filename=filename,
            object_key=object_key,
            content_hash=content_hash,
            byte_size=len(data),
            mime_type=mime_type,
            request_key=request_key,
            request_hash=request_hash,
            status="pending",
            processor_profile_revision=current_processor_profile(),
        )
        self.session.add(revision)
        await self.session.flush()
        await self._enqueue(
            revision,
            action="upload",
            request_key=request_key,
            request_hash=request_hash,
            file_version=item.version,
        )
        return revision

    async def _enqueue(
        self,
        revision: ProjectFileRevision,
        *,
        action: str,
        request_key: str,
        request_hash: str,
        file_version: int,
    ) -> EventLog:
        """Freeze the accepted attempt and processor contract in one schema-2 event."""
        event, _outbox = await EventService(self.session).append_with_outbox(
            project_id=self.project_id,
            aggregate_type="ProjectFileRevision",
            aggregate_id=revision.id,
            event_type=EXTRACTION_EVENT,
            topic=EXTRACTION_EVENT,
            actor_id=self.actor.id,
            schema_version=2,
            payload={
                "revision_id": str(revision.id),
                "request_key": request_key,
                "request_hash": request_hash,
                "action": action,
                "accepted_attempt": revision.attempt,
                "file_version": file_version,
                "processor_profile_revision": revision.processor_profile_revision,
            },
        )
        return event

    async def _acceptance_event(self, revision_id: UUID, request_key: str) -> EventLog | None:
        event: EventLog | None = await self.session.scalar(
            select(EventLog).where(
                EventLog.project_id == self.project_id,
                EventLog.aggregate_id == revision_id,
                EventLog.event_type == EXTRACTION_EVENT,
                EventLog.schema_version == 2,
                EventLog.payload["request_key"].as_string() == request_key,
            )
        )
        return event

    async def unlink(self, file_id: UUID, *, expected_version: int) -> ProjectFile:
        await self._authorize()
        item = await self._file(file_id, lock=True)
        if item.version != expected_version:
            raise ConflictError("Source association changed")
        if item.detached_at is None:
            item.detached_at = datetime.now(UTC)
            item.version += 1
        await self.session.flush()
        return item

    async def accept_extraction(
        self,
        revision_id: UUID,
        *,
        action: str,
        request_key: str,
        expected_file_version: int,
        expected_attempt: int,
        expected_extraction_id: UUID | None,
        processor_profile_revision: str,
    ) -> ExtractionAcceptance:
        """Accept one explicit retry/reparse under a frozen processor contract.

        Same key + same hash returns the original acceptance even after the current
        state moved; a different payload under a used key is a conflict. The accepted
        attempt is only recorded here; the worker performs the local work.
        """
        if action not in {"retry", "reparse"}:
            raise ValidationAppError("Unsupported extraction action")
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid extraction request key")
        if len(processor_profile_revision) != 64 or any(
            character not in "0123456789abcdef" for character in processor_profile_revision
        ):
            raise ValidationAppError("Invalid processor profile revision")
        request_hash = _acceptance_hash(
            revision_id=revision_id,
            action=action,
            request_key=request_key,
            expected_file_version=expected_file_version,
            expected_attempt=expected_attempt,
            expected_extraction_id=expected_extraction_id,
            processor_profile_revision=processor_profile_revision,
        )
        item, revision = await self.read_revision(revision_id)
        if processor_profile_revision != current_processor_profile():
            raise SourceAcceptanceError(
                "SOURCE_PROFILE_DRIFT",
                "The processor profile changed; refresh capabilities before accepting",
            )
        # Match upload's project -> file -> revision lock order.
        await self.session.scalar(
            select(Project).where(Project.id == self.project_id).with_for_update()
        )
        item = await self._file(item.id, lock=True)
        await self.session.refresh(revision, with_for_update=True)
        replay = await self._acceptance_event(revision.id, request_key)
        if replay is not None:
            if replay.payload.get("request_hash") != request_hash:
                raise SourceAcceptanceError(
                    "SOURCE_REQUEST_KEY_REUSED",
                    "Extraction request key already used for a different request",
                )
            accepted_attempt = replay.payload.get("accepted_attempt")
            accepted_profile = replay.payload.get("processor_profile_revision")
            if not isinstance(accepted_attempt, int) or not isinstance(accepted_profile, str):
                # A stored receipt without the frozen facts cannot be replayed.
                raise SourceAcceptanceError(
                    "SOURCE_STALE_ACCEPTANCE", "Stored extraction acceptance is incomplete"
                )
            return ExtractionAcceptance(
                file_revision_id=revision.id,
                accepted_attempt=accepted_attempt,
                event_id=replay.event_id,
                processor_profile_revision=accepted_profile,
                action=str(replay.payload.get("action")),
            )
        if item.detached_at or item.content_version != revision.number:
            raise SourceAcceptanceError(
                "SOURCE_UNAVAILABLE", "Only the current available source can be reprocessed"
            )
        if item.version != expected_file_version or revision.attempt != expected_attempt:
            raise SourceAcceptanceError(
                "SOURCE_STALE_ACCEPTANCE", "Source acceptance basis is stale"
            )
        if action == "reparse" and expected_extraction_id is None:
            raise ValidationAppError("Reparse requires the current extraction id")
        if (
            expected_extraction_id is not None
            and revision.current_extraction_id != expected_extraction_id
        ):
            raise SourceAcceptanceError(
                "SOURCE_STALE_ACCEPTANCE", "Extraction pointer changed"
            )
        required_state = "failed" if action == "retry" else "parsed"
        if revision.status != required_state:
            raise SourceAcceptanceError(
                "SOURCE_STATE_CONFLICT",
                f"{action} requires a {required_state} source",
            )
        revision.status = "pending"
        revision.attempt += 1
        revision.error_code = None
        revision.processor_profile_revision = processor_profile_revision
        event = await self._enqueue(
            revision,
            action=action,
            request_key=request_key,
            request_hash=request_hash,
            file_version=item.version,
        )
        return ExtractionAcceptance(
            file_revision_id=revision.id,
            accepted_attempt=revision.attempt,
            event_id=event.event_id,
            processor_profile_revision=processor_profile_revision,
            action=action,
        )

    async def extract(
        self, revision_id: UUID, *, expected_attempt: int | None = None
    ) -> ProjectFileRevision:
        """Idempotent local work. Old results never replace the current file version."""
        item, revision = await self.read_revision(revision_id)
        attempt = revision.attempt if expected_attempt is None else expected_attempt
        if revision.status != "pending" or item.detached_at or revision.attempt != attempt:
            return revision
        # The accepted attempt is bound to one processor contract. A changed profile
        # (or a legacy row without a frozen profile) never runs under today's tools.
        frozen_profile = revision.processor_profile_revision
        profile_error: str | None = None
        if frozen_profile is None:
            profile_error = "source_profile_legacy"
        elif frozen_profile != current_processor_profile():
            profile_error = "source_profile_drift"
        # Local storage/CPU only. A temporary store failure leaves the durable
        # pending event recoverable; an invalid document becomes a per-file error.
        data = await self._original_bytes(revision)
        if profile_error is not None:
            parsed, error = None, profile_error
        else:
            try:
                parsed = await self._parse(revision, data)
                error = None
            except SourceParseError as exc:
                parsed, error = None, exc.code
        # Same lock order as retry/unlink; duplicate deliveries are harmless.
        item = await self._file(item.id, lock=True)
        await self.session.refresh(revision, with_for_update=True)
        if revision.status != "pending" or item.detached_at or revision.attempt != attempt:
            return revision
        if error is not None or parsed is None:
            revision.status = "failed"
            revision.error_code = error
            revision.parser_version = None
            await self.session.flush()
            return revision
        extraction = await self._append_extraction(item, revision, parsed)
        revision.status = "parsed"
        revision.error_code = None
        revision.parser_version = parsed.parser_version
        # Forward-only pointer: an older attempt can never become current again.
        revision.current_extraction_id = extraction.id
        await self.session.flush()
        return revision

    async def _parse(self, revision: ProjectFileRevision, data: bytes) -> ParsedSource:
        """Page-ranged PDFs resume from verified block receipts; other formats parse once."""
        extension = PurePosixPath(revision.filename.replace("\\", "/")).suffix.lower()
        if extension == ".pdf":
            return await parse_pdf_with_blocks(
                data,
                store=self.store,
                project_id=self.project_id,
                content_hash=revision.content_hash,
                revision_id=revision.id,
                attempt=revision.attempt,
            )
        return await asyncio.to_thread(
            parse_source, filename=revision.filename, data=data
        )

    async def _append_extraction(
        self,
        item: ProjectFile,
        revision: ProjectFileRevision,
        parsed: ParsedSource,
    ) -> SourceExtraction:
        """Append one immutable snapshot; the caller already holds the revision lock."""
        extraction = SourceExtraction(
            project_id=self.project_id,
            file_id=item.id,
            file_revision_id=revision.id,
            attempt=revision.attempt,
            parser_key=parsed.parser_key,
            parser_version=parsed.parser_version,
            content_hash=_fragment_content_hash(parsed),
            extraction_schema_version=parsed.extraction_schema_version,
            coverage=(
                {**parsed.coverage, "limitations": list(parsed.limitations)}
                if parsed.limitations
                else parsed.coverage
            ),
            processor_evidence=parsed.processor_evidence,
            completed_at=datetime.now(UTC),
        )
        self.session.add(extraction)
        await self.session.flush()
        self.session.add_all(
            [
                SourceFragment(
                    project_id=self.project_id,
                    extraction_id=extraction.id,
                    file_revision_id=revision.id,
                    ordinal=fragment.ordinal,
                    locator_kind=fragment.locator_kind,
                    locator=fragment.locator,
                    text_content=fragment.text,
                    content_hash=hashlib.sha256(fragment.text.encode()).hexdigest(),
                    extraction_method=fragment.extraction_method,
                    processor_ref=fragment.processor_ref,
                    evidence_meta=fragment.evidence_meta,
                )
                for fragment in parsed.fragments
            ]
        )
        await self.session.flush()
        return extraction

    async def read_extraction(self, extraction_id: UUID) -> SourceExtraction:
        await self._authorize()
        extraction = await self.session.scalar(
            select(SourceExtraction).where(
                SourceExtraction.id == extraction_id,
                SourceExtraction.project_id == self.project_id,
            )
        )
        if extraction is None:
            raise NotFoundError("source extraction not found")
        return extraction

    async def list_fragments(
        self,
        extraction_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        locator_kind: str | None = None,
    ) -> tuple[list[SourceFragment], int]:
        """Return one ordered page plus the total count for the same filter."""
        await self._authorize()
        if not 1 <= limit <= 200 or offset < 0:
            raise ValidationAppError("Invalid fragment page")
        condition = [
            SourceFragment.extraction_id == extraction_id,
            SourceFragment.project_id == self.project_id,
        ]
        if locator_kind is not None:
            condition.append(SourceFragment.locator_kind == locator_kind)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(SourceFragment).where(*condition)
            )
            or 0
        )
        items = list(
            await self.session.scalars(
                select(SourceFragment)
                .where(*condition)
                .order_by(SourceFragment.ordinal)
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total


    async def fail_extraction(self, revision_id: UUID, *, expected_attempt: int) -> None:
        """Record a safe infrastructure failure; explicit retry remains per file."""
        item, revision = await self.read_revision(revision_id)
        item = await self._file(item.id, lock=True)
        await self.session.refresh(revision, with_for_update=True)
        if (
            revision.status == "pending"
            and item.detached_at is None
            and revision.attempt == expected_attempt
        ):
            revision.status = "failed"
            revision.error_code = "source_processing_failed"
            await self.session.flush()
