"""Source-use declarations and their intersection with egress admission.

A declaration never grants copyright and never overrides the project egress
policy: both must allow an outbound path. Revocation is a new immutable revision,
and an artifact keeps the revision identity it actually consumed.
"""

from __future__ import annotations

import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.source_use_models import (
    USE_PURPOSES,
    ArtifactSourceUse,
    SourceUseRevision,
    SourceUseSubject,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class SourceUseService:
    """Project-scoped declarations; the caller owns the transaction."""

    def __init__(self, session: AsyncSession, *, actor: User, project: Project) -> None:
        self._session = session
        self._actor = actor
        self._project = project

    async def _subject(
        self, *, file_revision_id: UUID | None, artifact_id: UUID | None,
    ) -> SourceUseSubject | None:
        query = select(SourceUseSubject).where(
            SourceUseSubject.project_id == self._project.id
        )
        if file_revision_id is not None:
            query = query.where(SourceUseSubject.file_revision_id == file_revision_id)
        elif artifact_id is not None:
            query = query.where(SourceUseSubject.artifact_id == artifact_id)
        else:
            raise ValidationAppError("来源必须指定原件修订或既有素材")
        return cast(SourceUseSubject | None, await self._session.scalar(query))

    async def find_subject(
        self, *, file_revision_id: UUID | None = None, artifact_id: UUID | None = None,
    ) -> SourceUseSubject | None:
        return await self._subject(
            file_revision_id=file_revision_id, artifact_id=artifact_id,
        )

    async def current(self, subject_id: UUID) -> SourceUseRevision | None:
        subject = await self._session.scalar(
            select(SourceUseSubject).where(
                SourceUseSubject.id == subject_id,
                SourceUseSubject.project_id == self._project.id,
            )
        )
        if subject is None:
            raise NotFoundError("source subject not found")
        if subject.current_revision_id is None:
            return None
        return cast(
            SourceUseRevision | None,
            await self._session.scalar(
                select(SourceUseRevision).where(
                    SourceUseRevision.id == subject.current_revision_id,
                    SourceUseRevision.project_id == self._project.id,
                )
            ),
        )

    async def list_subjects(
        self, *, limit: int = 50, offset: int = 0,
    ) -> list[SourceUseSubject]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid source-use page")
        return list(
            await self._session.scalars(
                select(SourceUseSubject)
                .where(SourceUseSubject.project_id == self._project.id)
                .order_by(SourceUseSubject.created_at, SourceUseSubject.id)
                .limit(limit)
                .offset(offset)
            )
        )

    async def declare(
        self,
        *,
        file_revision_id: UUID | None = None,
        artifact_id: UUID | None = None,
        allowed_uses: list[str],
        statement: str,
        evidence_note: str = "",
        request_key: str,
        state: str = "declared",
        expected_version: int | None = None,
    ) -> SourceUseRevision:
        if state not in {"declared", "revoked"}:
            raise ValidationAppError(
                "来源用途状态只能是 declared 或 revoked",
                details={"code": "SOURCE_USE_STATE_INVALID"},
            )
        revoke = state == "revoked"
        if (file_revision_id is None) == (artifact_id is None):
            raise ValidationAppError("来源必须且只能是原件修订或既有素材之一")
        uses = sorted({str(value) for value in allowed_uses})
        if any(value not in USE_PURPOSES for value in uses):
            raise ValidationAppError(
                "用途必须属于受支持的来源用途集合", details={"code": "SOURCE_USE_PURPOSE_INVALID"},
            )
        if revoke:
            uses = []
        if not revoke and not statement.strip():
            raise ValidationAppError(
                "声明用途时必须写明来源声明", details={"code": "SOURCE_USE_STATEMENT_REQUIRED"},
            )
        if len(statement) > 4000 or len(evidence_note) > 4000 or not 1 <= len(request_key) <= 160:
            raise ValidationAppError("来源声明内容或请求键不合规")
        request_hash = _hash(
            {
                "file_revision_id": str(file_revision_id) if file_revision_id else None,
                "artifact_id": str(artifact_id) if artifact_id else None,
                "allowed_uses": uses,
                "statement": statement,
                "evidence_note": evidence_note,
                "state": state,
            }
        )
        await self._session.scalar(
            select(Project.id).where(Project.id == self._project.id).with_for_update()
        )
        subject = await self._subject(
            file_revision_id=file_revision_id, artifact_id=artifact_id,
        )
        if subject is None:
            if expected_version not in (None, 0):
                raise ConflictError(
                    "该来源尚无声明，请以期望版本0建立",
                    details={"code": "SOURCE_USE_VERSION_CONFLICT", "current_version": 0},
                )
            subject = SourceUseSubject(
                project_id=self._project.id,
                file_revision_id=file_revision_id,
                artifact_id=artifact_id,
                version=1,
            )
            self._session.add(subject)
            await self._session.flush()
        replay = await self._session.scalar(
            select(SourceUseRevision).where(
                SourceUseRevision.project_id == self._project.id,
                SourceUseRevision.request_key == request_key,
            )
        )

        if replay is not None:
            if replay.request_hash != request_hash:
                raise ConflictError(
                    "同一请求键已用于不同的来源声明",
                    details={"code": "SOURCE_USE_REQUEST_CONFLICT"},
                )
            return replay
        if (
            expected_version is not None
            and subject.current_revision_id is not None
            and expected_version != subject.version
        ):
            raise ConflictError(
                "来源用途声明已更新，请刷新后重新确认",
                details={
                    "code": "SOURCE_USE_VERSION_CONFLICT",
                    "current_version": subject.version,
                },
            )
        if subject.current_revision_id is not None and not revoke:
            current = await self.current(subject.id)
            if current is not None and current.state == "revoked":
                raise ConflictError(
                    "已撤回的来源不能原地恢复，请建立新的来源声明",
                    details={"code": "SOURCE_USE_REVOKED"},
                )
        next_number = subject.version + 1
        content_hash = _hash(
            {
                "state": state if (uses or revoke) else "unreviewed",
                "allowed_uses": uses,
                "statement": statement,
                "evidence_note": evidence_note,
            }
        )
        revision = SourceUseRevision(
            project_id=self._project.id,
            subject_id=subject.id,
            number=next_number - 1,
            origin_expected_version=subject.version,
            result_version=next_number,
            state=state if (uses or revoke) else "unreviewed",
            allowed_uses=uses,
            statement=statement,
            evidence_note=evidence_note,
            content_hash=content_hash,
            request_key=request_key,
            request_hash=request_hash,
        )
        self._session.add(revision)
        await self._session.flush()
        subject.current_revision_id = revision.id
        subject.version = next_number
        await self._session.flush()
        return revision

    async def gate(
        self, *, file_revision_ids: list[UUID], required_uses: list[str],
    ) -> dict[str, object]:
        """Return which inputs may be used for the required purposes right now."""
        required = sorted({str(value) for value in required_uses})
        blocked: list[dict[str, object]] = []
        allowed_subjects: list[UUID] = []
        for revision_id in file_revision_ids:
            subject = await self._subject(file_revision_id=revision_id, artifact_id=None)
            if subject is None or subject.current_revision_id is None:
                blocked.append({"file_revision_id": str(revision_id), "code": "UNDECLARED"})
                continue
            revision = await self.current(subject.id)
            if revision is None or revision.state == "revoked":
                blocked.append({"file_revision_id": str(revision_id), "code": "REVOKED"})
                continue
            declared = {str(value) for value in revision.allowed_uses}
            if not set(required) <= declared:
                blocked.append(
                    {"file_revision_id": str(revision_id), "code": "USE_NOT_DECLARED"},
                )
                continue
            allowed_subjects.append(subject.id)
        return {
            "allowed": not blocked,
            "blocked": blocked,
            "allowed_subject_ids": [str(value) for value in allowed_subjects],
        }

    async def impact(
        self, *, subject_id: UUID, limit: int = 50, cursor: str | None = None,
    ) -> tuple[list[ArtifactSourceUse], str | None]:
        """Read how this project's artifacts consumed one declaration (current project only)."""
        if not 1 <= limit <= 100:
            raise ValidationAppError("Invalid impact page")
        subject = await self._session.scalar(
            select(SourceUseSubject).where(
                SourceUseSubject.id == subject_id,
                SourceUseSubject.project_id == self._project.id,
            )
        )
        if subject is None:
            raise NotFoundError("source subject not found")
        query = (
            select(ArtifactSourceUse)
            .where(
                ArtifactSourceUse.project_id == self._project.id,
                ArtifactSourceUse.source_subject_id == subject_id,
            )
            .order_by(ArtifactSourceUse.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            try:
                query = query.where(ArtifactSourceUse.id > UUID(cursor))
            except ValueError as exc:
                raise ValidationAppError("Invalid impact cursor") from exc
        rows = list(await self._session.scalars(query))
        page = rows[:limit]
        next_cursor = str(page[-1].id) if len(rows) > limit else None
        return page, next_cursor

    async def record_artifact_source_use(
        self,
        *,
        artifact_id: UUID,
        source_subject_id: UUID,
        source_project_id: UUID,
        source_revision_id: UUID,
        consumer_node_run_id: UUID,
        input_role: str,
        source_access_kind: str = "private",
    ) -> ArtifactSourceUse:
        await self._session.scalar(
            select(Project.id).where(Project.id == self._project.id).with_for_update()
        )
        row = ArtifactSourceUse(
            project_id=self._project.id,
            artifact_id=artifact_id,
            source_subject_id=source_subject_id,
            source_project_id=source_project_id,
            source_revision_id=source_revision_id,
            consumer_node_run_id=consumer_node_run_id,
            input_role=input_role,
            source_access_kind=source_access_kind,
        )
        self._session.add(row)
        await self._session.flush()
        return row


__all__ = ["SourceUseService"]


async def vision_source_revisions(
    session: AsyncSession,
    *,
    project_id: UUID,
    artifact_ids: list[UUID],
    file_revision_ids: tuple[UUID, ...] = (),
) -> list[str]:
    """Freeze current declared uses of every private source of every attachment."""
    revisions: set[str] = set()
    if file_revision_ids:
        rows = (
            await session.execute(
                select(SourceUseSubject.file_revision_id, SourceUseRevision)
                .join(
                    SourceUseRevision, SourceUseRevision.id == SourceUseSubject.current_revision_id
                )
                .where(
                    SourceUseSubject.project_id == project_id,
                    SourceUseRevision.project_id == project_id,
                    SourceUseRevision.subject_id == SourceUseSubject.id,
                    SourceUseSubject.file_revision_id.in_(file_revision_ids),
                )
            )
        ).all()
        if {file_id for file_id, _ in rows} != set(file_revision_ids) or any(
            r.state != "declared" or "external_processing" not in r.allowed_uses for _, r in rows
        ):
            raise _vision_denied()
        revisions.update(str(r.id) for _, r in rows)
    for root in artifact_ids:
        seen: set[UUID] = set()
        frontier = {root}
        found = False
        for _ in range(33):
            if not frontier:
                break
            seen.update(frontier)
            if len(seen) > 1024:
                raise _vision_denied()
            edges = list(
                await session.scalars(
                    select(ArtifactSourceUse)
                    .where(
                        ArtifactSourceUse.project_id == project_id,
                        ArtifactSourceUse.artifact_id.in_(frontier),
                    )
                    .limit(1025)
                )
            )
            if len(edges) > 1024 or any(
                row.source_project_id != project_id or row.source_access_kind != "private"
                for row in edges
            ):
                raise _vision_denied()
            required = {row.source_subject_id for row in edges}
            subjects = list(
                await session.scalars(
                    select(SourceUseSubject)
                    .where(
                        SourceUseSubject.project_id == project_id,
                        (SourceUseSubject.artifact_id.in_(frontier))
                        | SourceUseSubject.id.in_(required),
                    )
                    .limit(1025)
                    .execution_options(populate_existing=True)
                )
            )
            if len(subjects) > 1024 or required.difference(subject.id for subject in subjects):
                raise _vision_denied()
            rows = list(
                await session.scalars(
                    select(SourceUseRevision)
                    .join(
                        SourceUseSubject,
                        SourceUseSubject.current_revision_id == SourceUseRevision.id,
                    )
                    .where(
                        SourceUseSubject.id.in_([subject.id for subject in subjects]),
                        SourceUseRevision.subject_id == SourceUseSubject.id,
                        SourceUseRevision.project_id == project_id,
                    )
                )
            )
            if len(rows) != len(subjects) or any(
                row.state != "declared" or "external_processing" not in row.allowed_uses
                for row in rows
            ):
                raise _vision_denied()
            revisions.update(str(row.id) for row in rows)
            found = found or bool(rows)
            frontier = {s.artifact_id for s in subjects if s.artifact_id is not None} - seen
        if frontier or not found:
            raise _vision_denied()
    return sorted(revisions)


def _vision_denied() -> ValidationAppError:
    return ValidationAppError(
        "请先核对该画面及其来源的外部处理许可", details={"code": "SOURCE_USE_BLOCKED"}
    )
