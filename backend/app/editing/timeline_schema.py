"""Edit timeline schema versions and Save-time source validation (I9-01).

The timeline is owned by the session version, but a clip's *source* is a claim
about production truth.  Schema 2 makes that claim explicit and typed:

* ``schema_version`` 1 (or absent) keeps the historical shot-only meaning; it is
  stored verbatim and is never silently upgraded.
* ``schema_version`` 2 requires a typed ``source`` per clip.  Only the
  ``shot_formal`` kind can be verified today: the source artifact must be the
  shot's current formal video in the same project.  ``asset_version`` and
  ``public_material`` sources need the adoption/public-material qualification
  path, so they are refused fail-closed instead of being trusted from JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion, AssetVersionReference, Scene, Shot
from app.execution.models import Artifact
from app.shared.errors import ValidationAppError

TIMELINE_SCHEMA_V1 = 1
TIMELINE_SCHEMA_V2 = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({TIMELINE_SCHEMA_V1, TIMELINE_SCHEMA_V2})

ClipSourceKind = Literal["shot_formal", "asset_version", "public_material"]
# Kinds whose eligibility can be proven from data this service already owns.
VERIFIABLE_SOURCE_KINDS: frozenset[str] = frozenset({"shot_formal", "asset_version"})


class ClipSource(BaseModel):
    """Typed provenance for one clip; only the fields of its own kind may be set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ClipSourceKind
    shot_id: UUID | None = None
    artifact_id: UUID | None = None
    asset_id: UUID | None = None
    asset_version_id: UUID | None = None
    publication_id: UUID | None = None
    publication_item_id: UUID | None = None
    public_asset_link_id: UUID | None = None


class TimelineClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    subtitle: str = ""
    transition: dict[str, Any] | None = None
    source: ClipSource
    audio_source: ClipSource | None = None
    # Server-written observation of the source at Save; never client-authoritative.
    selection_snapshot: dict[str, Any] | None = None


class TimelineDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    clips: list[TimelineClip]
    metadata: dict[str, Any] = Field(default_factory=dict)


def _invalid(message: str, **details: object) -> ValidationAppError:
    return ValidationAppError(message, details={"code": "EDIT_TIMELINE_INVALID", **details})


def declared_schema_version(timeline: dict[str, object]) -> int:
    raw = timeline.get("schema_version", TIMELINE_SCHEMA_V1)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _invalid("timeline schema_version must be an integer")
    if raw not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValidationAppError(
            "timeline schema version is not supported",
            details={"code": "EDIT_SCHEMA_UNSUPPORTED", "schema_version": raw},
        )
    return raw


def _source_of(clip: dict[str, object], index: int) -> ClipSource:
    raw = clip.get("source")
    if raw is None:
        raise _invalid("schema 2 clip has no source", clip_index=index)
    try:
        source = ClipSource.model_validate(raw)
    except ValidationError as exc:
        raise _invalid("clip source is not a supported shape", clip_index=index) from exc
    _require_kind_fields(source, index=index)
    return source


def _require_kind_fields(source: ClipSource, *, index: int) -> None:
    if source.kind == "shot_formal":
        if source.shot_id is None or source.artifact_id is None:
            raise _invalid("shot_formal source needs shot_id and artifact_id", clip_index=index)
        if any(
            value is not None
            for value in (
                source.asset_id,
                source.asset_version_id,
                source.publication_id,
                source.publication_item_id,
                source.public_asset_link_id,
            )
        ):
            raise _invalid("shot_formal source carries foreign identity", clip_index=index)
        return
    if source.kind == "asset_version":
        if source.asset_id is None or source.asset_version_id is None:
            raise _invalid(
                "asset_version source needs asset_id and asset_version_id", clip_index=index
            )
        return
    if source.publication_id is None or source.publication_item_id is None:
        raise _invalid(
            "public_material source needs publication_id and publication_item_id",
            clip_index=index,
        )


def _reject_duplicates_and_order(clips: list[TimelineClip]) -> None:
    ids = [clip.id for clip in clips]
    if len(set(ids)) != len(ids):
        raise _invalid("clip ids must be unique")
    orders = sorted(clip.order for clip in clips)
    if orders != list(range(1, len(clips) + 1)):
        raise _invalid("clip order must be 1..n without gaps")


def parse_schema2(timeline: dict[str, object]) -> TimelineDocument:
    """Validate a schema 2 document without touching the database."""
    raw_clips = timeline.get("clips", [])
    if not isinstance(raw_clips, list):
        raise _invalid("timeline clips must be a list")
    clips: list[TimelineClip] = []
    for index, raw in enumerate(raw_clips):
        if not isinstance(raw, dict):
            raise _invalid("clip must be an object", clip_index=index)
        source = _source_of(cast(dict[str, object], raw), index)
        payload = {**cast(dict[str, object], raw), "source": source.model_dump(mode="json")}
        try:
            clips.append(TimelineClip.model_validate(payload))
        except ValidationError as exc:
            raise _invalid("clip is not a supported shape", clip_index=index) from exc
    _reject_duplicates_and_order(clips)
    metadata = timeline.get("metadata", {})
    if not isinstance(metadata, dict):
        raise _invalid("timeline metadata must be an object")
    return TimelineDocument(
        schema_version=TIMELINE_SCHEMA_V2,
        clips=clips,
        metadata=cast(dict[str, Any], metadata),
    )


async def _verify_asset_version(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
) -> Artifact:
    """An adopted asset version is usable only while its current formal media exists."""
    assert source.asset_id is not None and source.asset_version_id is not None
    version = await session.get(AssetVersion, source.asset_version_id)
    asset = await session.get(Asset, source.asset_id)
    if (
        version is None
        or asset is None
        or version.project_id != project_id
        or version.asset_id != asset.id
        or asset.project_id != project_id
        or asset.status == "recycled"
    ):
        raise ValidationAppError(
            "clip asset version is not available in this project",
            details={"code": "EDIT_SOURCE_NOT_ADOPTED", "clip_index": index},
        )
    if version.status != "formal" or asset.current_version_id != version.id:
        raise ValidationAppError(
            "clip asset version is not the current formal version",
            details={"code": "EDIT_SOURCE_NOT_ADOPTED", "clip_index": index},
        )
    artifact = await session.scalar(
        select(Artifact)
        .join(AssetVersionReference, AssetVersionReference.artifact_id == Artifact.id)
        .where(
            AssetVersionReference.asset_version_id == version.id,
            Artifact.artifact_type == "video",
            Artifact.storage_state == "available",
            Artifact.deleted_at.is_(None),
        )
        .order_by(AssetVersionReference.sort_order, Artifact.id)
        .limit(1)
    )
    if artifact is None:
        raise ValidationAppError(
            "clip asset version has no playable media",
            details={"code": "EDIT_SOURCE_NO_MEDIA", "clip_index": index},
        )
    return artifact


async def _verify_source(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
    episode_id: UUID | None,
) -> Artifact | None:
    """Verify one clip source and return the media artifact it resolves to."""
    if source.kind == "shot_formal":
        await _verify_shot_formal(
            session, project_id=project_id, source=source, index=index, episode_id=episode_id
        )
        return await session.get(Artifact, source.artifact_id) if source.artifact_id else None
    return await _verify_asset_version(session, project_id=project_id, source=source, index=index)


async def _verify_shot_formal(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
    episode_id: UUID | None = None,
) -> None:
    assert source.shot_id is not None and source.artifact_id is not None
    shot = await session.scalar(
        select(Shot).where(Shot.id == source.shot_id, Shot.project_id == project_id)
    )
    if shot is None:
        raise _invalid("clip shot is not in this project", clip_index=index)
    if episode_id is not None:
        belongs = await session.scalar(
            select(Scene.id)
            .join(Shot, Shot.scene_id == Scene.id)
            .where(Shot.id == shot.id, Scene.episode_id == episode_id)
        )
        if belongs is None:
            raise ValidationAppError(
                "episode-scoped session cannot hold a clip from another episode",
                details={"code": "EDIT_CLIP_OUT_OF_EPISODE", "clip_index": index},
            )
    if shot.formal_video_artifact_id != source.artifact_id:
        raise ValidationAppError(
            "clip source is not the shot's current formal video",
            details={"code": "EDIT_SOURCE_NOT_FORMAL", "clip_index": index},
        )
    artifact = await session.get(Artifact, source.artifact_id)
    if artifact is None or artifact.project_id != project_id or artifact.deleted_at is not None:
        raise ValidationAppError(
            "clip source artifact is unavailable",
            details={"code": "EDIT_SOURCE_NOT_FORMAL", "clip_index": index},
        )


async def _observe_source(
    session: AsyncSession,
    *,
    clip_id: str,
    source: ClipSource,
    session_version: int,
    media_artifact: Artifact | None,
) -> dict[str, Any]:
    """Server-side observation of what this clip actually points at now.

    This is an observation, not a second Formal fact: it records the identity the
    timeline was saved against so a later render/export can prove what the editor
    saw.  Only verified kinds reach here.
    """
    return {
        "schema_version": TIMELINE_SCHEMA_V2,
        "session_version": session_version,
        "clip_id": clip_id,
        "kind": source.kind,
        "identity": source.model_dump(mode="json", exclude_none=True),
        "artifact_hash": media_artifact.content_hash if media_artifact else None,
        "artifact_id": str(media_artifact.id) if media_artifact else None,
        "confirmed_at": datetime.now(UTC).isoformat(),
    }


def _same_observation(previous: object, current: dict[str, Any]) -> bool:
    if not isinstance(previous, dict):
        return False
    return bool(
        previous.get("kind") == current["kind"]
        and previous.get("identity") == current["identity"]
        and previous.get("artifact_hash") == current["artifact_hash"]
    )


async def normalize_timeline_for_save(
    session: AsyncSession,
    *,
    project_id: UUID,
    timeline: dict[str, object],
    episode_id: UUID | None = None,
    previous_timeline: dict[str, object] | None = None,
    session_version: int | None = None,
) -> dict[str, object]:
    """Return the exact document to persist, or fail closed.

    Schema 1 keeps its historical meaning and is returned unchanged: an explicit
    user save is the only moment a timeline may become schema 2.  Every schema 2
    clip gains a server-written ``selection_snapshot``; when the source is
    unchanged the previous legal observation is reused instead of re-dating it.
    """
    version = declared_schema_version(timeline)
    if version == TIMELINE_SCHEMA_V1:
        # Schema 1 carries no on-disk marker: strip an explicitly-sent default so
        # historical documents keep their exact stored shape.
        return {key: value for key, value in timeline.items() if key != "schema_version"}
    document = parse_schema2(timeline)
    previous_by_clip = _previous_snapshots(previous_timeline)
    stored: list[dict[str, Any]] = []
    for index, clip in enumerate(document.clips):
        media: Artifact | None = None
        for source in (clip.source, clip.audio_source):
            if source is None:
                continue
            if source.kind not in VERIFIABLE_SOURCE_KINDS:
                raise ValidationAppError(
                    "clip source cannot be verified yet; save is refused",
                    details={
                        "code": "EDIT_SOURCE_UNVERIFIED",
                        "clip_index": index,
                        "kind": source.kind,
                    },
                )
            verified = await _verify_source(
                session,
                project_id=project_id,
                source=source,
                index=index,
                episode_id=episode_id,
            )
            media = media or verified
        payload = clip.model_dump(mode="json")
        previous = previous_by_clip.get(clip.id)
        observed = await _observe_source(
            session,
            clip_id=clip.id,
            source=clip.source,
            session_version=session_version or 1,
            media_artifact=media,
        )
        if _same_observation(previous, observed):
            # Unchanged source: keep the original observation and its timestamp.
            snapshot = dict(cast(dict[str, Any], previous))
        else:
            initial = (
                previous.get("initial_source")
                if isinstance(previous, dict) and previous.get("initial_source")
                else clip.source.model_dump(mode="json", exclude_none=True)
            )
            snapshot = {**observed, "initial_source": initial}
        payload["selection_snapshot"] = snapshot
        stored.append(payload)
    return {
        "schema_version": TIMELINE_SCHEMA_V2,
        "clips": stored,
        "metadata": document.metadata,
    }


def _previous_snapshots(previous_timeline: dict[str, object] | None) -> dict[str, dict[str, Any]]:
    """Index the previous document's own snapshots by clip id, if it was schema 2."""
    if not previous_timeline or previous_timeline.get("schema_version") != TIMELINE_SCHEMA_V2:
        return {}
    raw_clips = previous_timeline.get("clips")
    if not isinstance(raw_clips, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for raw in raw_clips:
        if not isinstance(raw, dict):
            continue
        clip_id = raw.get("id")
        snapshot = raw.get("selection_snapshot")
        if isinstance(clip_id, str) and isinstance(snapshot, dict):
            indexed[clip_id] = cast(dict[str, Any], snapshot)
    return indexed


__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "TIMELINE_SCHEMA_V1",
    "TIMELINE_SCHEMA_V2",
    "ClipSource",
    "TimelineClip",
    "TimelineDocument",
    "declared_schema_version",
    "normalize_timeline_for_save",
    "parse_schema2",
]
