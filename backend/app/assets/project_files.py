"""Project-scoped originals and versioned local extraction; no creative writes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.source_parser import MAX_SOURCE_BYTES, SourceParseError, parse_source
from app.events.models import EventLog
from app.events.service import EventService
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore


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
            excerpts=[],
        )
        self.session.add(revision)
        await self.session.flush()
        await self._enqueue(revision)
        return revision

    async def _enqueue(
        self,
        revision: ProjectFileRevision,
        *,
        retry_key: str | None = None,
    ) -> None:
        await EventService(self.session).append_with_outbox(
            project_id=self.project_id,
            aggregate_type="ProjectFileRevision",
            aggregate_id=revision.id,
            event_type="project_file.extraction_requested",
            topic="project_file.extraction_requested",
            actor_id=self.actor.id,
            payload={"revision_id": str(revision.id), "retry_key": retry_key},
        )

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

    async def retry_extraction(self, revision_id: UUID, *, request_key: str) -> ProjectFileRevision:
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid retry request key")
        item, revision = await self.read_revision(revision_id)
        # Match upload's project -> file -> revision lock order. Outbox inserts
        # acquire project FK locks too, so taking the file lock first can deadlock.
        await self.session.scalar(
            select(Project)
            .where(
                Project.id == self.project_id,
            )
            .with_for_update()
        )
        item = await self._file(item.id, lock=True)
        await self.session.refresh(revision, with_for_update=True)
        replay = await self.session.scalar(
            select(EventLog.event_id).where(
                EventLog.project_id == self.project_id,
                EventLog.aggregate_id == revision.id,
                EventLog.event_type == "project_file.extraction_requested",
                EventLog.payload["retry_key"].as_string() == request_key,
            )
        )
        if replay is not None:
            return revision
        if item.detached_at or item.content_version != revision.number:
            raise ConflictError("Only the current available source can be retried")
        if revision.status != "failed":
            raise ConflictError("Source extraction is not failed")
        revision.status = "pending"
        revision.attempt += 1
        revision.error_code = None
        await self._enqueue(revision, retry_key=request_key)
        return revision

    async def extract(
        self, revision_id: UUID, *, expected_attempt: int | None = None
    ) -> ProjectFileRevision:
        """Idempotent local work. Old results never replace the current file version."""
        item, revision = await self.read_revision(revision_id)
        attempt = revision.attempt if expected_attempt is None else expected_attempt
        if revision.status != "pending" or item.detached_at or revision.attempt != attempt:
            return revision
        # Local storage/CPU only. A temporary store failure leaves the durable
        # pending event recoverable; an invalid document becomes a per-file error.
        data = await self._original_bytes(revision)
        try:
            parsed = await asyncio.to_thread(parse_source, filename=revision.filename, data=data)
            excerpts = [asdict(excerpt) for excerpt in parsed.excerpts]
            error = None
            parser_version = parsed.parser_version
        except SourceParseError as exc:
            excerpts, error, parser_version = [], exc.code, None
        # Same lock order as retry/unlink; duplicate deliveries are harmless.
        item = await self._file(item.id, lock=True)
        await self.session.refresh(revision, with_for_update=True)
        if revision.status != "pending" or item.detached_at or revision.attempt != attempt:
            return revision
        revision.status = "failed" if error else "parsed"
        revision.error_code = error
        revision.parser_version = parser_version
        revision.excerpts = excerpts
        await self.session.flush()
        return revision

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
