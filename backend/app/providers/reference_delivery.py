"""Short-lived, one-artifact HTTPS delivery for outbound Provider references."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_admission import EgressAdmission
from app.access.models import Project
from app.assets.models import AssetVersion
from app.config import Settings, get_settings
from app.execution.branches import branch_priority
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.providers.models import ArtifactReferenceToken
from app.shared.errors import NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store

if TYPE_CHECKING:
    from app.providers.runtime import ResolvedReference


@dataclass(frozen=True, slots=True)
class ArtifactReferenceGrant:
    url: str
    artifact_id: UUID
    content_hash: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PublicArtifactReference:
    artifact_id: UUID
    project_id: UUID
    object_key: str
    mime_type: str
    content_hash: str
    expires_at: datetime
    publication_id: UUID | None = None
    publication_item_id: UUID | None = None
    public_asset_link_id: UUID | None = None


def _public_origin(settings: Settings) -> str:
    origin = settings.reference_public_base_url.strip().rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise ValidationAppError(
            "REFERENCE_PUBLIC_BASE_URL must be a public HTTPS origin",
            details={"code": "REFERENCE_DELIVERY_NOT_CONFIGURED"},
        )
    if parsed.hostname == "localhost":
        raise ValidationAppError(
            "REFERENCE_PUBLIC_BASE_URL must not use a local host",
            details={"code": "REFERENCE_DELIVERY_NOT_CONFIGURED"},
        )
    try:
        if ipaddress.ip_address(parsed.hostname).is_private:
            raise ValidationAppError(
                "REFERENCE_PUBLIC_BASE_URL must not use a private address",
                details={"code": "REFERENCE_DELIVERY_NOT_CONFIGURED"},
            )
    except ValueError:
        pass
    return origin


def _latest_for_shot(
    rows: list[NodeRun],
    *,
    shot_id: str,
    target_snapshot: dict[str, object] | None = None,
) -> NodeRun | None:
    matching = [
        run
        for run in rows
        if str((run.input_snapshot or {}).get("shot_id") or "") == shot_id
        and branch_priority(run.input_snapshot, target_snapshot) is not None
    ]
    return max(
        matching,
        key=lambda run: (
            branch_priority(run.input_snapshot, target_snapshot) or 0,
            run.attempt_no,
            run.created_at,
            str(run.id),
        ),
        default=None,
    )


async def approved_first_frame_for_video(
    session: AsyncSession,
    *,
    video_run: NodeRun,
) -> Artifact:
    """Resolve the current Shot's explicit keyframe through GraphEdge lineage."""
    shot_id = str((video_run.input_snapshot or {}).get("shot_id") or "").strip()
    if not shot_id:
        raise ValidationAppError(
            "video run has no shot lineage",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    video_node = await session.get(GraphNode, video_run.graph_node_id)
    if video_node is None or video_node.node_key != "video":
        raise ValidationAppError("reference delivery requires a video NodeRun")
    keyframe_node = (
        await session.execute(
            select(GraphNode)
            .select_from(GraphEdge)
            .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
            .where(GraphEdge.graph_version_id == video_run.graph_version_id)
            .where(GraphEdge.downstream_node_id == video_node.id)
            .where(GraphEdge.required.is_(True))
            .where(GraphNode.node_key == "keyframe")
        )
    ).scalar_one_or_none()
    if keyframe_node is None:
        raise ValidationAppError(
            "video has no required keyframe edge",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    keyframe_runs = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == video_run.project_id,
                    NodeRun.graph_version_id == video_run.graph_version_id,
                    NodeRun.graph_node_id == keyframe_node.id,
                )
            )
        )
        .scalars()
        .all()
    )
    keyframe_run = _latest_for_shot(
        keyframe_runs,
        shot_id=shot_id,
        target_snapshot=video_run.input_snapshot,
    )
    if keyframe_run is None or keyframe_run.result_artifact_id is None:
        raise ValidationAppError(
            "keyframe Artifact is missing",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    artifact = await session.get(Artifact, keyframe_run.result_artifact_id)
    if (
        artifact is None
        or artifact.project_id != video_run.project_id
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
        or artifact.artifact_type != "image"
        or not artifact.mime_type.startswith("image/")
    ):
        raise ValidationAppError(
            "keyframe Artifact is unavailable",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    return artifact


async def issue_artifact_reference(
    session: AsyncSession,
    *,
    artifact: Artifact,
    workspace_id: UUID,
    created_by_run_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    settings: Settings | None = None,
    destination_id: UUID | None = None,
    processing_location: str = "external",
    publication_id: UUID | None = None,
    publication_item_id: UUID | None = None,
    public_asset_link_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> ArtifactReferenceGrant:
    if (created_by_run_id is None) == (created_by_user_id is None):
        raise ValueError("reference grant requires exactly one audited creator")
    project = await session.get(Project, artifact.project_id)
    if project is None or project.workspace_id != workspace_id:
        raise NotFoundError("reference Artifact not found")
    if (
        artifact.storage_state != "available"
        or artifact.deleted_at is not None
        or artifact.artifact_type != "image"
        or not artifact.mime_type.startswith("image/")
    ):
        raise ValidationAppError(
            "reference Artifact is unavailable",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    # A public reference URL is an outbound path: the project policy is checked
    # before a token exists, so a refusal leaves no redeemable grant behind.
    admission = await EgressAdmission(session).decide(
        project,
        purpose="reference_delivery",
        required_purposes=["reference_delivery"],
        destination_id=destination_id,
        processing_location=processing_location,
    )
    if not admission.allowed:
        raise ValidationAppError(
            "项目外发策略不允许签发本次引用地址",
            details={"code": admission.reason_code},
        )
    cfg = settings or get_settings()
    origin = _public_origin(cfg)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(seconds=cfg.reference_token_ttl_seconds)
    if public_asset_link_id is not None and owner_user_id is None:
        from app.assets.public_asset_models import ProjectPublicAssetLink

        link_owner = await session.scalar(
            select(ProjectPublicAssetLink.owner_user_id).where(
                ProjectPublicAssetLink.id == public_asset_link_id
            )
        )
        owner_user_id = link_owner
    public_identity = (publication_id, publication_item_id, public_asset_link_id, owner_user_id)
    if any(value is not None for value in public_identity) and not all(
        value is not None for value in public_identity
    ):
        raise ValidationAppError(
            "public reference tokens need the complete public identity",
            details={"code": "REFERENCE_PUBLIC_IDENTITY_INCOMPLETE"},
        )
    if public_asset_link_id is not None:
        from app.assets.public_asset_models import (
            ProjectPublicAssetLink,
            PublicAssetPublication,
            PublicAssetPublicationItem,
        )

        link = await session.get(ProjectPublicAssetLink, public_asset_link_id)
        publication = (
            await session.get(PublicAssetPublication, publication_id)
            if publication_id is not None
            else None
        )
        item = (
            await session.get(PublicAssetPublicationItem, publication_item_id)
            if publication_item_id is not None
            else None
        )
        if (
            link is None
            or publication is None
            or item is None
            or link.project_id != artifact.project_id
            or link.publication_id != publication.id
            or publication.source_project_id != artifact.project_id
            or item.publication_id != publication.id
            or item.artifact_id != artifact.id
            or link.detached_at is not None
            or publication.status != "available"
        ):
            raise ValidationAppError(
                "public reference identity is not eligible",
                details={"code": "REFERENCE_PUBLIC_NOT_AVAILABLE"},
            )
    session.add(
        ArtifactReferenceToken(
            workspace_id=workspace_id,
            project_id=artifact.project_id,
            artifact_id=artifact.id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by_run_id=created_by_run_id,
            created_by_user_id=created_by_user_id,
            egress_admission=admission.evidence(),
            publication_id=publication_id,
            publication_item_id=publication_item_id,
            public_asset_link_id=public_asset_link_id,
            owner_user_id=owner_user_id,
        )
    )
    await session.flush()
    return ArtifactReferenceGrant(
        url=f"{origin}/api/v1/provider-references/{token}",
        artifact_id=artifact.id,
        content_hash=artifact.content_hash,
        expires_at=expires_at,
    )


def runtime_reference_transport(compiler: object, manifest: object) -> str | None:
    """The reference transport the selected compiler consumes for ``manifest``.

    Compilers declare their transport as a class attribute; revisions whose
    wire semantics differ per catalog contract (e.g. Agnes contract revisions
    take public HTTPS URLs while legacy revisions embed bytes) override with
    ``reference_transport_for(manifest)``. Returns ``None`` when undeclared.
    """

    method = getattr(compiler, "reference_transport_for", None)
    if callable(method):
        value = method(manifest)
        return value if isinstance(value, str) else None
    value = getattr(compiler, "reference_transport", None)
    return value if isinstance(value, str) else None


async def resolve_reference_for_runtime(
    session: AsyncSession,
    *,
    project: Project,
    run: NodeRun,
    role: str,
    artifact: Artifact | None,
    content_bytes: bytes | None,
    mime_type: str,
    fingerprint: str | None,
    provider_type: str,
    reference_transport: str | None = None,
    publication_id: UUID | None = None,
    publication_item_id: UUID | None = None,
    public_asset_link_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> ResolvedReference:
    """Build the runtime reference using the compiler's declared transport.

    Transport-specific URL versus bytes policy belongs in the provider
    delivery layer, not in the shared execution orchestration module. The
    selected compiler's declaration decides (``runtime_reference_transport``);
    callers that have not adopted it fail closed to the stored-bytes path.
    """
    from app.providers.runtime import ResolvedReference

    # Public-URL compilers (Ark, MiniMax, Agnes contract revisions) receive
    # short-lived signed grants; every bytes compiler gets the stored bytes.
    if reference_transport == "public_url":
        if artifact is None:
            raise ValidationAppError(
                "public-URL reference requires a bound image artifact",
                details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
            )
        grant = await issue_artifact_reference(
            session,
            artifact=artifact,
            workspace_id=project.workspace_id,
            created_by_run_id=run.id,
            publication_id=publication_id,
            publication_item_id=publication_item_id,
            public_asset_link_id=public_asset_link_id,
            owner_user_id=owner_user_id,
        )
        return ResolvedReference(
            role=role,
            artifact_id=artifact.id,
            content_url=grant.url,
            mime_type=artifact.mime_type or mime_type,
            fingerprint=artifact.content_hash,
            byte_size=artifact.byte_size,
            duration_seconds=(
                float(artifact.duration_seconds) if artifact.duration_seconds is not None else None
            ),
            width=artifact.width,
            height=artifact.height,
        )
    if content_bytes is None:
        raise ValidationAppError(
            "reference bytes are required",
            details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
        )
    return ResolvedReference(
        role=role,
        artifact_id=artifact.id if artifact is not None else UUID(int=0),
        content_bytes=content_bytes,
        mime_type=mime_type,
        fingerprint=fingerprint,
        byte_size=artifact.byte_size if artifact is not None else len(content_bytes),
        duration_seconds=(
            float(artifact.duration_seconds)
            if artifact is not None and artifact.duration_seconds is not None
            else None
        ),
        width=artifact.width if artifact is not None else None,
        height=artifact.height if artifact is not None else None,
    )


_SQLITE_REFERENCE_USE_DENIED = """
WITH RECURSIVE media(id, depth) AS (
        SELECT :artifact, 0
        UNION
        SELECT s.artifact_id, m.depth + 1
        FROM media m
        JOIN artifact_source_uses u ON u.artifact_id = m.id
        JOIN source_use_subjects s ON s.id = u.source_subject_id
        WHERE s.artifact_id IS NOT NULL AND m.depth < 33
    ), bounded AS (SELECT id, depth FROM media LIMIT 1025),
    required(id) AS (
        SELECT s.id FROM bounded m JOIN source_use_subjects s ON s.artifact_id = m.id
        UNION
        SELECT u.source_subject_id FROM bounded m
          JOIN artifact_source_uses u ON u.artifact_id = m.id
          LIMIT 1025
    )
    SELECT 1 FROM required q
    LEFT JOIN source_use_subjects s ON s.id = q.id
    LEFT JOIN source_use_revisions r ON r.id = s.current_revision_id AND r.subject_id = s.id
    WHERE (r.state IS NULL OR r.state != 'declared')
       OR NOT EXISTS (SELECT 1 FROM json_each(r.allowed_uses) WHERE value = 'external_processing')
       OR (:is_public AND NOT EXISTS (SELECT 1 FROM json_each(r.allowed_uses)
                                    WHERE value = 'library_reference'))
    UNION ALL SELECT 1 WHERE :is_public AND NOT EXISTS (SELECT 1 FROM required)
    UNION ALL SELECT 1 FROM bounded WHERE depth > 32
    UNION ALL SELECT 1 WHERE (SELECT count(*) FROM bounded) > 1024
    UNION ALL SELECT 1 WHERE (SELECT count(*) FROM required) > 1024 LIMIT 1
"""


async def resolve_public_reference(
    session: AsyncSession,
    *,
    token: str,
) -> PublicArtifactReference:
    if len(token) < 32 or len(token) > 128:
        raise NotFoundError("reference not found")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT artifact_id, project_id, object_key, mime_type,
                           content_hash, expires_at, publication_id,
                           publication_item_id, public_asset_link_id
                    FROM app.artifact_reference_for_token(:token_hash)
                    """
                    ),
                    {"token_hash": token_hash},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError("reference not found")
        return PublicArtifactReference(
            artifact_id=row["artifact_id"],
            project_id=row["project_id"],
            object_key=str(row["object_key"]),
            mime_type=str(row["mime_type"]),
            content_hash=str(row["content_hash"]),
            expires_at=row["expires_at"],
            publication_id=row["publication_id"],
            publication_item_id=row["publication_item_id"],
            public_asset_link_id=row["public_asset_link_id"],
        )
    record = await session.scalar(
        select(ArtifactReferenceToken).where(
            ArtifactReferenceToken.token_hash == token_hash,
            ArtifactReferenceToken.expires_at > datetime.now(UTC),
        )
    )
    artifact = await session.get(Artifact, record.artifact_id) if record else None
    if (
        record is None
        or artifact is None
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
    ):
        raise NotFoundError("reference not found")
    blocked = await session.scalar(text(_SQLITE_REFERENCE_USE_DENIED), {
        "artifact": artifact.id.hex, "is_public": record.publication_id is not None,
    })
    if blocked:
        raise NotFoundError("reference not found")
    if record.publication_id is not None:
        from app.assets.public_asset_models import (
            ProjectPublicAssetLink,
            PublicAssetPublication,
            PublicAssetPublicationItem,
        )

        publication = await session.get(PublicAssetPublication, record.publication_id)
        link = (
            await session.get(ProjectPublicAssetLink, record.public_asset_link_id)
            if record.public_asset_link_id is not None
            else None
        )
        item = (
            await session.get(
                PublicAssetPublicationItem, record.publication_item_id
            )
            if record.publication_item_id is not None
            else None
        )
        version = (
            await session.get(AssetVersion, publication.source_asset_version_id)
            if publication is not None
            else None
        )
        if (
            publication is None
            or link is None
            or item is None
            or version is None
            or publication.status != "available"
            or publication.withdrawn_at is not None
            or link.detached_at is not None
            or version.status != "formal"
            or item.artifact_id != artifact.id
        ):
            raise NotFoundError("reference not found")
    return PublicArtifactReference(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        object_key=artifact.object_key,
        mime_type=artifact.mime_type,
        content_hash=artifact.content_hash,
        expires_at=record.expires_at,
        publication_id=record.publication_id,
        publication_item_id=record.publication_item_id,
        public_asset_link_id=record.public_asset_link_id,
    )


async def read_public_reference_bytes(
    reference: PublicArtifactReference,
    *,
    store: ObjectStore | None = None,
) -> bytes:
    obj_store = store or get_object_store()
    try:
        data = await obj_store.get_bytes(object_key=reference.object_key)
    except Exception as exc:
        raise NotFoundError("reference not found") from exc
    if not data or hashlib.sha256(data).hexdigest() != reference.content_hash:
        raise NotFoundError("reference not found")
    return data
