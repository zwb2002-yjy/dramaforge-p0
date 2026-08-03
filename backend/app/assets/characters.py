"""Character + canonical reference registration (P0 §3.1.9)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, Character, CharacterReference
from app.consistency.face_policy import approved_face_threshold
from app.consistency.image_embed import embedding_from_image_bytes
from app.execution.artifact_lineage import get_or_create_artifact
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


@dataclass(frozen=True)
class CharacterWithCanonical:
    character_id: UUID
    asset_id: UUID
    name: str
    canonical_object_key: str
    canonical_artifact_id: UUID
    canonical_content_hash: str
    canonical_mime_type: str
    similarity_threshold: float
    embedding_dim: int


async def register_lead_character(
    session: AsyncSession,
    *,
    project_id: UUID,
    name: str,
    locked_prompt: str,
    canonical_image_bytes: bytes,
    store: ObjectStore | None = None,
) -> CharacterWithCanonical:
    """Create character asset + canonical reference with 512-d embedding from image."""
    if not canonical_image_bytes:
        raise ValidationAppError("canonical image required")
    obj = store or get_object_store()
    emb = embedding_from_image_bytes(canonical_image_bytes)
    if len(emb) != 512:
        raise ValidationAppError("embedding dim must be 512")

    asset = Asset(
        project_id=project_id,
        kind="character",
        name=name,
        description=f"Lead character {name}",
        status="active",
        metadata_json={"role": "lead"},
    )
    session.add(asset)
    await session.flush()
    char = Character(
        id=asset.id,
        locked_prompt=locked_prompt,
        negative_prompt="",
        calibration_state="calibrated",
        similarity_threshold=approved_face_threshold(),
    )
    session.add(char)
    await session.flush()

    object_key = f"projects/{project_id}/characters/{asset.id}/canonical.png"
    stored = await obj.put_bytes(
        object_key=object_key,
        data=canonical_image_bytes,
        mime_type="image/png",
    )
    artifact = await get_or_create_artifact(
        session,
        project_id=project_id,
        artifact_type="image",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=None,
    )
    ref = CharacterReference(
        character_id=char.id,
        artifact_id=artifact.id,
        object_key=artifact.object_key,
        reference_kind="canonical",
        is_canonical=True,
        face_embedding=emb,
        embedding_model_version="content-hash-v1",
    )
    session.add(ref)
    await session.flush()
    return CharacterWithCanonical(
        character_id=char.id,
        asset_id=asset.id,
        name=name,
        canonical_object_key=artifact.object_key,
        canonical_artifact_id=artifact.id,
        canonical_content_hash=artifact.content_hash,
        canonical_mime_type=artifact.mime_type,
        similarity_threshold=approved_face_threshold(),
        embedding_dim=len(emb),
    )


async def require_canonical_for_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    character_id: UUID | None = None,
) -> CharacterReference:
    """Reject generation when project lead has no canonical reference."""
    q = (
        select(CharacterReference)
        .join(Character, Character.id == CharacterReference.character_id)
        .join(Asset, Asset.id == Character.id)
        .where(Asset.project_id == project_id)
        .where(CharacterReference.is_canonical.is_(True))
    )
    if character_id is not None:
        q = q.where(Character.id == character_id)
    ref = (await session.execute(q.limit(1))).scalar_one_or_none()
    if ref is None:
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")
    if ref.artifact_id is None or not ref.object_key or not ref.face_embedding:
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")
    return ref
