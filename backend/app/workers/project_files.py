"""Recoverable local source processing in the existing dispatcher process.

The committed revision is the work receipt. Outbox remains the transactional
notification channel; Redis stream retention cannot lose pending extraction.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User, Workspace
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.project_files import ProjectFileService
from app.shared.db import set_rls_context
from app.storage.minio_store import ObjectStore

logger = logging.getLogger(__name__)
FAILURE_RECEIPT_TIMEOUT_SECONDS = 5.0


@dataclass
class SourceScanCursor:
    after_revision_id: UUID | None = None


async def process_project_files(
    factory: Callable[[], AsyncSession],
    *,
    store: ObjectStore,
    limit: int = 5,
    cursor: SourceScanCursor | None = None,
) -> dict[str, int]:
    if not 1 <= limit <= 100:
        raise ValueError("Invalid source batch size")
    scan = cursor if cursor is not None else SourceScanCursor()
    async with asyncio.timeout(10), factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            rows = list(
                (
                    await session.execute(
                        text("SELECT * FROM app.pending_project_file_contexts(:limit, :after)"),
                        {"limit": limit, "after": scan.after_revision_id},
                    )
                ).mappings()
            )
        else:
            # Portable test database, never a fallback for failed PostgreSQL RLS.
            rows = list(
                (
                    await session.execute(
                        select(
                            ProjectFileRevision.id.label("revision_id"),
                            Workspace.owner_user_id.label("owner_user_id"),
                            Workspace.id.label("workspace_id"),
                            Project.id.label("project_id"),
                            ProjectFileRevision.attempt,
                        )
                        .join(ProjectFile, ProjectFile.id == ProjectFileRevision.file_id)
                        .join(Project, Project.id == ProjectFile.project_id)
                        .join(Workspace, Workspace.id == Project.workspace_id)
                        .join(User, User.id == Workspace.owner_user_id)
                        .where(
                            ProjectFileRevision.status == "pending",
                            ProjectFile.detached_at.is_(None),
                            Project.deleted_at.is_(None),
                            User.is_active.is_(True),
                        )
                        .where(
                            true()
                            if scan.after_revision_id is None
                            else ProjectFileRevision.id > scan.after_revision_id
                        )
                        .order_by(ProjectFileRevision.id)
                        .limit(limit)
                    )
                ).mappings()
            )
    counts = {"processed": 0, "failed": 0}
    if not rows:
        scan.after_revision_id = None
    for scope in rows:
        # Failed rows cannot monopolize the next page; an empty scan wraps.
        scan.after_revision_id = scope["revision_id"]
        try:
            async with asyncio.timeout(30), factory() as session:
                await set_rls_context(
                    session,
                    user_id=scope["owner_user_id"],
                    workspace_id=scope["workspace_id"],
                    project_id=scope["project_id"],
                )
                session.info["selected_workspace_id"] = scope["workspace_id"]
                actor = await session.get(User, scope["owner_user_id"])
                if actor is None or not actor.is_active:
                    continue
                service = ProjectFileService(
                    session, store=store, actor=actor, project_id=scope["project_id"]
                )
                result = await service.extract(
                    scope["revision_id"], expected_attempt=scope["attempt"]
                )
                await session.commit()
                counts["failed" if result.status == "failed" else "processed"] += 1
        except Exception as exc:
            # A bad/missing original does not starve subsequent files. DB outages
            # that also prevent failure recording leave pending work discoverable.
            logger.warning(
                "Source extraction %s failed (%s)", scope["revision_id"], type(exc).__name__
            )
            counts["failed"] += 1
            try:
                async with asyncio.timeout(FAILURE_RECEIPT_TIMEOUT_SECONDS), factory() as session:
                    await set_rls_context(
                        session,
                        user_id=scope["owner_user_id"],
                        workspace_id=scope["workspace_id"],
                        project_id=scope["project_id"],
                    )
                    session.info["selected_workspace_id"] = scope["workspace_id"]
                    actor = await session.get(User, scope["owner_user_id"])
                    if actor is not None and actor.is_active:
                        await ProjectFileService(
                            session,
                            store=store,
                            actor=actor,
                            project_id=scope["project_id"],
                        ).fail_extraction(scope["revision_id"], expected_attempt=scope["attempt"])
                        await session.commit()
            except Exception as record_error:
                logger.warning(
                    "Source failure receipt unavailable (%s)", type(record_error).__name__
                )
    return counts
