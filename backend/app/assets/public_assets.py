"""Public asset library: publications, fixed items and project links (I5-01).

A publication freezes one adopted AssetVersion's safe display facts and its real media
references. Reads are owner-scoped across Workspaces; the cross-project DTO never
carries source project/asset identities, object keys, private research or prompts.
Availability is recomputed from the source version facts on every read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.domain_events import emit
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.assets.public_asset_models import (
    ProjectPublicAssetLink,
    PublicAssetPublication,
    PublicAssetPublicationItem,
)
from app.shared.errors import AppError, NotFoundError, ValidationAppError


class PublicAssetConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)


@dataclass(frozen=True)
class PublicDisplay:
    name: str
    description: str
    style_labels: list[str]


@dataclass(frozen=True)
class PublicContent:
    object_key: str
    mime_type: str
    byte_size: int
    content_hash: str


@lru_cache(maxsize=1)
def _sqlite_public_item_sql() -> str:
    return (
        (Path(__file__).with_name("sql") / "public_item_content_v1.sql")
        .read_text(encoding="utf-8")
        .format(
            schema="",
            actor=":actor",
            workspace=":workspace",
            active_project=":project",
            project=":project",
            link=":link",
            publication=":publication",
            item=":item",
            permits_library=("EXISTS (SELECT 1 FROM json_each(r.allowed_uses) "
                             "WHERE value='library_reference')"),
        )
    )


async def _read_public_content(
    session: AsyncSession,
    actor: User,
    item_id: UUID,
    *,
    publication_id: UUID | None = None,
    project_id: UUID | None = None,
    link_id: UUID | None = None,
) -> PublicContent:
    identities = {
        "publication": publication_id,
        "item": item_id,
        "project": project_id,
        "link": link_id,
    }
    if session.get_bind().dialect.name == "postgresql":
        row = (
            (
                await session.execute(
                    text(
                        "SELECT object_key, mime_type, byte_size, content_hash "
                        "FROM app.public_item_content(:publication, :item, :project, :link)"
                    ),
                    identities,
                )
            )
            .mappings()
            .one_or_none()
        )
    else:
        params = {key: value.hex if value else None for key, value in identities.items()}
        workspace = session.info.get("selected_workspace_id")
        params.update(actor=actor.id.hex, workspace=UUID(str(workspace)).hex if workspace else None)
        row = (
            (await session.execute(text(_sqlite_public_item_sql()), params))
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise NotFoundError("public asset content not found")
    return PublicContent(**row)


@dataclass(frozen=True)
class PublicItemSummary:
    id: UUID
    media_kind: str
    role: str
    mime_type: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    preview_available: bool


@dataclass(frozen=True)
class PublicAssetRead:
    id: UUID
    kind: str
    safe_name: str
    safe_description: str
    style_labels: list[str]
    publication_hash: str
    revision: int
    status: str
    usable: bool
    reason_codes: list[str]
    items: list[PublicItemSummary]
    created_at: datetime


@dataclass(frozen=True)
class ProjectPublicLinkRead:
    id: UUID
    project_id: UUID
    publication_id: UUID
    local_label: str
    version: int
    detached_at: datetime | None
    availability: str


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_display(display: PublicDisplay) -> dict[str, object]:
    if not 1 <= len(display.name) <= 160:
        raise ValidationAppError(
            "Public display name is invalid", details={"code": "PUBLIC_DISPLAY_INVALID"}
        )
    if len(display.description) > 2_000:
        raise ValidationAppError(
            "Public display description is too long",
            details={"code": "PUBLIC_DISPLAY_INVALID"},
        )
    if len(display.style_labels) > 20 or any(
        not 1 <= len(label) <= 80 for label in display.style_labels
    ):
        raise ValidationAppError(
            "Public display labels are invalid", details={"code": "PUBLIC_DISPLAY_INVALID"}
        )
    return {
        "name": display.name,
        "description": display.description,
        "style_labels": sorted({label for label in display.style_labels}),
    }


class PublicAssetService:
    """Caller owns commit; reads and writes are owner-scoped, never source-project scoped."""

    def __init__(self, session: AsyncSession, *, actor: User) -> None:
        self.session = session
        self.actor = actor

    async def publish(
        self, asset_version_id: UUID, *, display: PublicDisplay
    ) -> PublicAssetRead:
        canonical = validate_display(display)
        version = await self.session.scalar(
            select(AssetVersion)
            .join(Asset, Asset.id == AssetVersion.asset_id)
            .where(AssetVersion.id == asset_version_id)
        )
        if version is None:
            raise NotFoundError("asset version not found")
        project = await self.session.scalar(
            select(Project).where(
                Project.id == version.project_id, Project.deleted_at.is_(None)
            )
        )
        if project is None:
            raise NotFoundError("source project not found")
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.id == project.workspace_id,
                Workspace.owner_user_id == self.actor.id,
            )
        )
        if workspace is None:
            raise NotFoundError("asset version not found")
        if version.status != "formal":
            raise PublicAssetConflictError(
                "PUBLIC_ASSET_SOURCE_NOT_FORMAL",
                "Only a formal asset version can be published",
            )
        existing = await self.session.scalar(
            select(PublicAssetPublication).where(
                PublicAssetPublication.source_asset_version_id == version.id
            )
        )
        if existing is not None:
            return await self.read(existing.id)
        references = list(
            await self.session.scalars(
                select(AssetVersionReference).where(
                    AssetVersionReference.asset_version_id == version.id
                )
            )
        )
        if not references:
            raise PublicAssetConflictError(
                "PUBLIC_ASSET_WITHOUT_MEDIA", "A publication needs at least one real media item"
            )
        publication_hash = _hash(
            [str(version.id), version.kind, canonical, [str(ref.id) for ref in references]]
        )
        publication = PublicAssetPublication(
            owner_user_id=self.actor.id,
            workspace_id=workspace.id,
            source_project_id=project.id,
            source_asset_id=version.asset_id,
            source_asset_version_id=version.id,
            kind=version.kind,
            safe_name=str(canonical["name"]),
            safe_description=str(canonical["description"]),
            safe_metadata={"style_labels": canonical["style_labels"]},
            publication_hash=publication_hash,
            status="available",
            revision=1,
        )
        self.session.add(publication)
        await self.session.flush()
        for reference in references:
            self.session.add(
                PublicAssetPublicationItem(
                    publication_id=publication.id,
                    owner_user_id=self.actor.id,
                    workspace_id=workspace.id,
                    source_project_id=project.id,
                    source_asset_version_id=version.id,
                    source_reference_id=reference.id,
                    artifact_id=reference.artifact_id,
                )
            )
        await self.session.flush()
        await emit(
            self.session,
            project_id=project.id,
            aggregate_type="PublicAssetPublication",
            aggregate_id=publication.id,
            event_type="public_asset.publication.created",
            payload={
                "publication_id": str(publication.id),
                "source_asset_version_id": str(version.id),
                "publication_hash": publication_hash,
                "item_count": len(references),
            },
            actor_id=self.actor.id,
        )
        return await self.read(publication.id)

    async def _publication(self, publication_id: UUID) -> PublicAssetPublication:
        publication = await self.session.scalar(
            select(PublicAssetPublication).where(
                PublicAssetPublication.id == publication_id,
                PublicAssetPublication.owner_user_id == self.actor.id,
            )
        )
        if publication is None:
            raise NotFoundError("public asset not found")
        return publication

    async def availability(
        self, publication: PublicAssetPublication
    ) -> tuple[str, bool, list[str]]:
        if publication.status == "withdrawn" or publication.withdrawn_at is not None:
            return "withdrawn", False, ["withdrawn"]
        version = await self.session.get(AssetVersion, publication.source_asset_version_id)
        if version is None or version.status != "formal":
            return "restricted", False, ["source_version_unavailable"]
        return "available", True, []

    async def _items(self, publication: PublicAssetPublication) -> list[PublicItemSummary]:
        rows = list(
            await self.session.scalars(
                select(PublicAssetPublicationItem)
                .where(PublicAssetPublicationItem.publication_id == publication.id)
                .order_by(PublicAssetPublicationItem.created_at, PublicAssetPublicationItem.id)
            )
        )
        from app.execution.models import Artifact

        references = {
            reference.id: reference
            for reference in await self.session.scalars(
                select(AssetVersionReference).where(
                    AssetVersionReference.id.in_(
                        [row.source_reference_id for row in rows]
                    )
                )
            )
        }
        summaries: list[PublicItemSummary] = []
        for row in rows:
            artifact = await self.session.get(Artifact, row.artifact_id)
            reference = references.get(row.source_reference_id)
            duration = getattr(artifact, "duration_seconds", None)
            summaries.append(
                PublicItemSummary(
                    id=row.id,
                    media_kind=str(getattr(artifact, "artifact_type", "") or ""),
                    role=str(reference.reference_role if reference is not None else ""),
                    mime_type=(
                        str(getattr(artifact, "mime_type", "") or "") or None
                    ),
                    width=getattr(artifact, "width", None),
                    height=getattr(artifact, "height", None),
                    duration_ms=int(duration * 1000) if duration is not None else None,
                    preview_available=artifact is not None,
                )
            )
        return summaries
    async def read(self, publication_id: UUID) -> PublicAssetRead:
        publication = await self._publication(publication_id)
        status, usable, reasons = await self.availability(publication)
        labels = publication.safe_metadata.get("style_labels")
        style_labels = [str(value) for value in labels] if isinstance(labels, list) else []
        return PublicAssetRead(
            id=publication.id,
            kind=publication.kind,
            safe_name=publication.safe_name,
            safe_description=publication.safe_description,
            style_labels=style_labels,
            publication_hash=publication.publication_hash,
            revision=publication.revision,
            status=status,
            usable=usable,
            reason_codes=reasons,
            items=await self._items(publication),
            created_at=publication.created_at,
        )

    async def read_content(self, publication_id: UUID, item_id: UUID) -> PublicContent:
        """Narrow owner-preview read: available publication + fixed item + real artifact."""
        return await _read_public_content(
            self.session, self.actor, item_id, publication_id=publication_id
        )

    async def list(
        self,
        *,
        query: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PublicAssetRead], int]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid public asset page")
        condition = [PublicAssetPublication.owner_user_id == self.actor.id]
        if kind:
            condition.append(PublicAssetPublication.kind == kind)
        if status:
            condition.append(PublicAssetPublication.status == status)
        if query:
            if len(query) > 200:
                raise ValidationAppError("Public asset query is too long")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            condition.append(
                PublicAssetPublication.safe_name.ilike(pattern, escape="\\")
                | PublicAssetPublication.safe_description.ilike(pattern, escape="\\")
            )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(PublicAssetPublication).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(PublicAssetPublication)
                .where(*condition)
                .order_by(PublicAssetPublication.created_at.desc(), PublicAssetPublication.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return [await self.read(row.id) for row in rows], total

    async def set_withdrawn(
        self, publication_id: UUID, *, expected_revision: int, withdrawn: bool
    ) -> PublicAssetRead:
        publication = await self.session.scalar(
            select(PublicAssetPublication)
            .where(
                PublicAssetPublication.id == publication_id,
                PublicAssetPublication.owner_user_id == self.actor.id,
            )
            .with_for_update()
        )
        if publication is None:
            raise NotFoundError("public asset not found")
        if publication.revision != expected_revision:
            raise PublicAssetConflictError(
                "PUBLIC_ASSET_STALE_REVISION", "Publication changed; reload before deciding"
            )
        if withdrawn:
            publication.status = "withdrawn"
            publication.withdrawn_at = datetime.now(UTC)
        else:
            version = await self.session.get(
                AssetVersion, publication.source_asset_version_id
            )
            if version is None or version.status != "formal":
                raise PublicAssetConflictError(
                    "PUBLIC_ASSET_SOURCE_UNAVAILABLE",
                    "The source version is no longer eligible",
                )
            publication.status = "available"
            publication.withdrawn_at = None
        publication.revision += 1
        await self.session.flush()
        await emit(
            self.session,
            project_id=publication.source_project_id,
            aggregate_type="PublicAssetPublication",
            aggregate_id=publication.id,
            event_type="public_asset.publication.withdrawn"
            if withdrawn
            else "public_asset.publication.restored",
            payload={
                "publication_id": str(publication.id),
                "withdrawn": withdrawn,
                "revision": publication.revision,
            },
            actor_id=self.actor.id,
        )
        return await self.read(publication.id)


class ProjectPublicAssetLinkService:
    def __init__(self, session: AsyncSession, *, actor: User, project_id: UUID) -> None:
        self.session = session
        self.actor = actor
        self.project_id = project_id

    async def _project(self) -> Project:
        return await ProjectService(self.session).get_project_for_owner(
            project_id=self.project_id, actor=self.actor
        )

    async def _publication(self, publication_id: UUID) -> PublicAssetPublication:
        publication = await self.session.scalar(
            select(PublicAssetPublication).where(
                PublicAssetPublication.id == publication_id,
                PublicAssetPublication.owner_user_id == self.actor.id,
            )
        )
        if publication is None:
            raise NotFoundError("public asset not found")
        return publication

    async def _availability(self, publication: PublicAssetPublication) -> str:
        if publication.status == "withdrawn" or publication.withdrawn_at is not None:
            return "withdrawn"
        version = await self.session.get(AssetVersion, publication.source_asset_version_id)
        if version is None or version.status != "formal":
            return "restricted"
        return "available"

    async def _read(self, link: ProjectPublicAssetLink) -> ProjectPublicLinkRead:
        publication = await self._publication(link.publication_id)
        return ProjectPublicLinkRead(
            id=link.id,
            project_id=link.project_id,
            publication_id=link.publication_id,
            local_label=link.local_label,
            version=link.version,
            detached_at=link.detached_at,
            availability=await self._availability(publication),
        )

    async def create(
        self, *, publication_id: UUID, local_label: str, request_key: str
    ) -> tuple[ProjectPublicLinkRead, bool]:
        if not 1 <= len(request_key) <= 160 or len(local_label) > 160:
            raise ValidationAppError("Invalid public link request")
        project = await self._project()
        publication = await self._publication(publication_id)
        request_hash = _hash(["link", str(project.id), str(publication.id), local_label])
        existing = await self.session.scalar(
            select(ProjectPublicAssetLink).where(
                ProjectPublicAssetLink.project_id == project.id,
                ProjectPublicAssetLink.request_key == request_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise PublicAssetConflictError(
                    "PUBLIC_LINK_KEY_REUSED", "Request key already used for a different link"
                )
            return await self._read(existing), False
        natural = await self.session.scalar(
            select(ProjectPublicAssetLink).where(
                ProjectPublicAssetLink.project_id == project.id,
                ProjectPublicAssetLink.publication_id == publication.id,
            )
        )
        if natural is not None:
            raise PublicAssetConflictError(
                "PUBLIC_LINK_EXISTS", "This publication is already linked to the project"
            )
        availability = await self._availability(publication)
        if availability != "available":
            raise PublicAssetConflictError(
                "PUBLIC_ASSET_NOT_AVAILABLE", "Only available publications can be linked"
            )
        link = ProjectPublicAssetLink(
            project_id=project.id,
            workspace_id=project.workspace_id,
            owner_user_id=self.actor.id,
            publication_id=publication.id,
            source_asset_version_id=publication.source_asset_version_id,
            local_label=local_label,
            version=1,
            request_key=request_key,
            request_hash=request_hash,
        )
        self.session.add(link)
        await self.session.flush()
        await emit(
            self.session,
            project_id=project.id,
            aggregate_type="ProjectPublicAssetLink",
            aggregate_id=link.id,
            event_type="public_asset.link.attached",
            payload={
                "link_id": str(link.id),
                "publication_id": str(publication.id),
                "version": link.version,
            },
            actor_id=self.actor.id,
        )
        return await self._read(link), True

    async def read_content(self, link_id: UUID, item_id: UUID) -> PublicContent:
        """Second narrow input: the consuming project reads through its own link."""
        project = await self._project()
        return await _read_public_content(
            self.session, self.actor, item_id, project_id=project.id, link_id=link_id
        )

    async def list(
        self, *, active: bool = True, limit: int = 50, offset: int = 0
    ) -> tuple[list[ProjectPublicLinkRead], int]:
        project = await self._project()
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid public link page")
        condition = [ProjectPublicAssetLink.project_id == project.id]
        if active:
            condition.append(ProjectPublicAssetLink.detached_at.is_(None))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ProjectPublicAssetLink).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(ProjectPublicAssetLink)
                .where(*condition)
                .order_by(ProjectPublicAssetLink.created_at, ProjectPublicAssetLink.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return [await self._read(row) for row in rows], total

    async def patch(
        self,
        link_id: UUID,
        *,
        expected_version: int,
        local_label: str | None,
        attached: bool | None,
    ) -> ProjectPublicLinkRead:
        project = await self._project()
        link = await self.session.scalar(
            select(ProjectPublicAssetLink)
            .where(
                ProjectPublicAssetLink.id == link_id,
                ProjectPublicAssetLink.project_id == project.id,
            )
            .with_for_update()
        )
        if link is None:
            raise NotFoundError("public asset link not found")
        if link.version != expected_version:
            raise PublicAssetConflictError(
                "PUBLIC_LINK_STALE_VERSION", "Link changed; reload before deciding"
            )
        if local_label is not None:
            if len(local_label) > 160:
                raise ValidationAppError("Local label is too long")
            link.local_label = local_label
        if attached is not None:
            if attached:
                publication = await self._publication(link.publication_id)
                if await self._availability(publication) != "available":
                    raise PublicAssetConflictError(
                        "PUBLIC_ASSET_NOT_AVAILABLE",
                        "Only available publications can be re-attached",
                    )
                link.detached_at = None
            else:
                link.detached_at = datetime.now(UTC)
        link.version += 1
        await self.session.flush()
        await emit(
            self.session,
            project_id=project.id,
            aggregate_type="ProjectPublicAssetLink",
            aggregate_id=link.id,
            event_type="public_asset.link.updated",
            payload={
                "link_id": str(link.id),
                "version": link.version,
                "detached": link.detached_at is not None,
            },
            actor_id=self.actor.id,
        )
        return await self._read(link)


__all__ = [
    "ProjectPublicAssetLinkService",
    "ProjectPublicLinkRead",
    "PublicAssetRead",
    "PublicAssetService",
    "PublicDisplay",
    "PublicItemSummary",
    "validate_display",
]
