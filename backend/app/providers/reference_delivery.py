"""Short-lived, one-artifact HTTPS delivery for outbound Provider references."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import Settings, get_settings
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.providers.models import ArtifactReferenceToken
from app.shared.errors import NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


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


def _latest_for_shot(rows: list[NodeRun], *, shot_id: str) -> NodeRun | None:
    matching = [
        run for run in rows if str((run.input_snapshot or {}).get("shot_id") or "") == shot_id
    ]
    return max(
        matching,
        key=lambda run: (run.attempt_no, run.created_at, str(run.id)),
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
    face_row = (
        await session.execute(
            select(GraphEdge, GraphNode)
            .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
            .where(GraphEdge.graph_version_id == video_run.graph_version_id)
            .where(GraphEdge.downstream_node_id == video_node.id)
            .where(GraphEdge.required.is_(True))
            .where(GraphNode.node_key == "face_review")
        )
    ).one_or_none()
    if face_row is None:
        raise ValidationAppError(
            "video has no required face review edge",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    _, face_node = face_row
    face_runs = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == video_run.project_id,
                    NodeRun.graph_version_id == video_run.graph_version_id,
                    NodeRun.graph_node_id == face_node.id,
                )
            )
        )
        .scalars()
        .all()
    )
    face_run = _latest_for_shot(face_runs, shot_id=shot_id)
    if (
        face_run is None
        or face_run.status not in {"completed", "cached"}
        or str((face_run.output_summary or {}).get("status")) not in {"passed", "not_applicable"}
    ):
        raise ValidationAppError(
            "video first frame has not passed Face Gate",
            details={"code": "UPSTREAM_TERMINAL_FAILURE"},
        )

    keyframe_node = (
        await session.execute(
            select(GraphNode)
            .join(GraphEdge, GraphEdge.upstream_node_id == GraphNode.id)
            .where(GraphEdge.graph_version_id == video_run.graph_version_id)
            .where(GraphEdge.downstream_node_id == face_node.id)
            .where(GraphEdge.required.is_(True))
            .where(GraphNode.node_key == "keyframe")
        )
    ).scalar_one_or_none()
    if keyframe_node is None:
        raise ValidationAppError(
            "Face Gate has no required keyframe edge",
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
    keyframe_run = _latest_for_shot(keyframe_runs, shot_id=shot_id)
    if keyframe_run is None or keyframe_run.result_artifact_id is None:
        raise ValidationAppError(
            "approved keyframe Artifact is missing",
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
            "approved keyframe Artifact is unavailable",
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
    cfg = settings or get_settings()
    origin = _public_origin(cfg)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(seconds=cfg.reference_token_ttl_seconds)
    session.add(
        ArtifactReferenceToken(
            workspace_id=workspace_id,
            project_id=artifact.project_id,
            artifact_id=artifact.id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by_run_id=created_by_run_id,
            created_by_user_id=created_by_user_id,
        )
    )
    await session.flush()
    return ArtifactReferenceGrant(
        url=f"{origin}/api/v1/provider-references/{token}",
        artifact_id=artifact.id,
        content_hash=artifact.content_hash,
        expires_at=expires_at,
    )


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
                           content_hash, expires_at
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
    return PublicArtifactReference(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        object_key=artifact.object_key,
        mime_type=artifact.mime_type,
        content_hash=artifact.content_hash,
        expires_at=record.expires_at,
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
