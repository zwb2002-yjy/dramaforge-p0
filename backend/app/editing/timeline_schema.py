"""Edit timeline schema versions and Save-time source validation (I9-01).

The timeline is owned by the session version, but a clip's *source* is a claim
about production truth.  Schema 2 makes that claim explicit and typed:

* ``schema_version`` 1 (or absent) keeps the historical shot-only meaning; it is
  stored verbatim and is never silently upgraded.
* ``schema_version`` 2 verifies formal shots, adopted asset versions and project
  publication links, and records the media observed at Save.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.from_artifact_service import (
    MediaSource,
    read_formal_clip_defaults,
    read_media_source,
)
from app.assets.models import Asset, AssetVersion, Scene, Shot
from app.assets.public_edit_media import read_public_edit_media
from app.editing.timeline_rules import clip_transition
from app.shared.errors import ValidationAppError

TIMELINE_SCHEMA_V1 = 1
TIMELINE_SCHEMA_V2 = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({TIMELINE_SCHEMA_V1, TIMELINE_SCHEMA_V2})

ClipSourceKind = Literal["shot_formal", "asset_version", "public_material"]


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
    source_in_seconds: float = Field(default=0, ge=0)
    source_out_seconds: float | None = Field(default=None, gt=0)
    muted: bool = False
    audio_volume: float = Field(default=1, ge=0, le=1)
    subtitle_enabled: bool | None = None
    subtitle: str = ""
    transition: dict[str, Any] | None = None
    source: ClipSource
    # An explicitly selected project-private voice uses the existing local audio identity.
    audio_id: UUID | None = None
    audio_source: ClipSource | None = None
    # Server-written observation of the source at Save; never client-authoritative.
    selection_snapshot: dict[str, Any] | None = None
    audio_selection_snapshot: dict[str, Any] | None = None


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
        if any(
            value is not None
            for value in (
                source.shot_id,
                source.artifact_id,
                source.publication_id,
                source.publication_item_id,
                source.public_asset_link_id,
            )
        ):
            raise _invalid("asset_version source carries foreign identity", clip_index=index)
        return
    if (
        source.publication_id is None
        or source.publication_item_id is None
        or source.public_asset_link_id is None
    ):
        raise _invalid(
            "public_material source needs publication_id, publication_item_id "
            "and public_asset_link_id",
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
    media_kind: str,
) -> MediaSource:
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
    artifact = await read_media_source(session, asset_version_id=version.id, media_kind=media_kind)
    if artifact is None:
        raise ValidationAppError(
            "clip asset version has no playable media",
            details={"code": "EDIT_SOURCE_NO_MEDIA", "clip_index": index},
        )
    return artifact


async def _verify_public_material(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
    media_kind: str,
    purpose: Literal["creation", "export"] = "creation",
) -> MediaSource:
    """A public clip resolves only through this project's own fixed link."""
    if (
        source.kind != "public_material" or source.publication_id is None
        or source.publication_item_id is None or source.public_asset_link_id is None
    ):
        raise _invalid("incomplete public media identity", clip_index=index)
    artifact = await read_public_edit_media(
        session, project_id=project_id, link_id=source.public_asset_link_id,
        publication_id=source.publication_id, item_id=source.publication_item_id, purpose=purpose,
    )
    if artifact is None:
        raise ValidationAppError(
            "public media is unavailable for this use",
            details={"code": "EDIT_SOURCE_NOT_ADOPTED", "clip_index": index},
        )
    if artifact.artifact_type != media_kind:
        raise ValidationAppError(
            "public media kind does not match the clip",
            details={"code": "EDIT_SOURCE_NO_MEDIA", "clip_index": index},
        )
    return artifact


class PublicRenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ClipSource
    clip_index: int = Field(ge=0)
    media_kind: Literal["video", "audio"]
    artifact_id: UUID
    artifact_hash: str


def public_render_inputs(
    document: dict[str, Any], *, include_muted: bool = False,
) -> list[PublicRenderInput]:
    inputs: list[PublicRenderInput] = []
    for index, clip in enumerate(document.get("clips", [])):
        if not isinstance(clip, dict):
            continue
        for source_field, snapshot_field, kind in (
            ("source", "selection_snapshot", "video"),
            ("audio_source", "audio_selection_snapshot", "audio"),
        ):
            raw = clip.get(source_field)
            if not isinstance(raw, dict) or raw.get("kind") != "public_material":
                continue
            if kind == "audio" and clip.get("muted") and not include_muted:
                continue
            saved = clip.get(snapshot_field) or {}
            if not isinstance(saved, dict):
                raise _invalid("invalid saved public media", clip_index=index)
            try:
                inputs.append(PublicRenderInput.model_validate({
                    "source": raw, "clip_index": index, "media_kind": kind,
                    "artifact_id": saved.get("artifact_id"),
                    "artifact_hash": saved.get("artifact_hash"),
                }))
            except ValidationError as exc:
                raise _invalid("invalid saved public media", clip_index=index) from exc
    return inputs


async def resolve_public_render_inputs(
    session: AsyncSession, project_id: UUID, inputs: list[PublicRenderInput],
) -> dict[UUID, MediaSource]:
    media: dict[UUID, MediaSource] = {}
    for item in inputs:
        source = await _verify_public_material(
            session, project_id=project_id, source=item.source, index=item.clip_index,
            media_kind=item.media_kind, purpose="export",
        )
        if source.id != item.artifact_id or source.content_hash != item.artifact_hash:
            raise _invalid("saved public media changed", clip_index=item.clip_index)
        media[source.id] = source
    return media


async def _verify_source(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
    media_kind: str,
    episode_id: UUID | None,
    previous: object = None,
) -> MediaSource | None:
    """Verify one clip source and return the media artifact it resolves to."""
    if source.kind == "shot_formal":
        if media_kind != "video":
            raise _invalid("a formal shot video cannot be used as an audio asset", clip_index=index)
        await _verify_shot_formal(
            session,
            project_id=project_id,
            source=source,
            index=index,
            episode_id=episode_id,
            previous=previous,
        )
        assert source.artifact_id is not None
        return await read_media_source(session, artifact_id=source.artifact_id)
    if source.kind == "asset_version":
        return await _verify_asset_version(
            session, project_id=project_id, source=source, index=index, media_kind=media_kind
        )
    return await _verify_public_material(
        session, project_id=project_id, source=source, index=index, media_kind=media_kind
    )


async def _verify_shot_formal(
    session: AsyncSession,
    *,
    project_id: UUID,
    source: ClipSource,
    index: int,
    episode_id: UUID | None = None,
    previous: object = None,
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
    artifact = await read_media_source(session, artifact_id=source.artifact_id)
    if (
        artifact is None
        or artifact.project_id != project_id
        or artifact.artifact_type != "video"
        or artifact.storage_state != "available"
    ):
        raise ValidationAppError(
            "clip source artifact is unavailable",
            details={"code": "EDIT_SOURCE_NOT_FORMAL", "clip_index": index},
        )
    # Only the previous server-owned document can attest an earlier Formal choice.
    already_selected = (
        isinstance(previous, dict)
        and previous.get("identity") == source.model_dump(mode="json", exclude_none=True)
        and previous.get("artifact_id") == str(artifact.id)
        and previous.get("artifact_hash") == artifact.content_hash
    )
    if shot.formal_video_artifact_id != source.artifact_id and not already_selected:
        raise ValidationAppError(
            "clip source is not the shot's current formal video",
            details={"code": "EDIT_SOURCE_NOT_FORMAL", "clip_index": index},
        )


async def _observe_source(
    session: AsyncSession,
    *,
    clip_id: str,
    source: ClipSource,
    session_version: int,
    media_artifact: MediaSource | None,
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


async def _preserve_clip_edits(
    session: AsyncSession,
    project_id: UUID,
    timeline: dict[str, object],
    previous: dict[str, object] | None,
) -> dict[str, object]:
    """Resolve legacy defaults only during an explicit typed edit; never rewrite old versions."""
    raw_clips = timeline.get("clips")
    if not isinstance(raw_clips, list):
        return timeline
    old_clips = (previous or {}).get("clips", [])
    prior = (
        {c.get("id"): c for c in old_clips if isinstance(c, dict)}
        if isinstance(old_clips, list)
        else {}
    )
    clips: list[object] = []
    for raw in raw_clips:
        if not isinstance(raw, dict):
            clips.append(raw)
            continue
        clip = dict(raw)
        old = prior.get(clip.get("id"), {})
        if clip.get("audio_id") == "":
            clip["audio_id"] = None
        current = clip.get("source")
        restore_voice = (
            "shot_id" not in clip and isinstance(current, dict) and current.get("kind") == "shot_formal"
            and "audio_id" in clip and clip["audio_id"] is None
            and not clip.get("audio_source") and not clip.get("muted")
            and old.get("source") == current and (old.get("audio_source") or old.get("audio_id") or old.get("muted"))
        )
        if restore_voice:
            ref = ClipSource.model_validate(current)
            if ref.shot_id is None or ref.artifact_id is None:
                raise _invalid("缺少镜头音轨来源")
            shot = await session.scalar(select(Shot).where(Shot.id==ref.shot_id, Shot.project_id==project_id))
            if shot is None:
                raise _invalid("镜头无法核对")
            voice, spoken = await read_formal_clip_defaults(
                session, project_id=project_id, shot_id=ref.shot_id, video_id=ref.artifact_id,
                composite_id=shot.formal_composite_artifact_id if shot.formal_video_artifact_id==ref.artifact_id else None)
            if voice is None and spoken != "":
                raise _invalid("此镜头原配音无法核对，请选择已有音轨或明确静音")
            clip["audio_id"]=voice
        # Navigation labels are only hints from the previous session. The typed source
        # and server-observed media are authoritative once a user elects to mix sources.
        if "shot_id" in clip or "artifact_id" in clip:
            if (
                not old
                or clip.get("shot_id") != old.get("shot_id")
                or clip.get("artifact_id") != old.get("artifact_id")
            ):
                raise _invalid("legacy source has changed; reload the saved edit")
            if not clip.get("source"):
                clip["source"] = {
                    "kind": "shot_formal",
                    "shot_id": clip.get("shot_id"),
                    "artifact_id": clip.get("artifact_id"),
                }
            shot = await session.scalar(
                select(Shot).where(
                    Shot.id == UUID(str(clip["shot_id"])), Shot.project_id == project_id
                )
            )
            if shot is None:
                raise _invalid("original shot is unavailable")
            need_voice = (
                not clip.get("muted") and not clip.get("audio_id") and not clip.get("audio_source")
            )
            need_caption = (
                clip.get("subtitle_enabled") is not False and clip.get("subtitle") is None
            )
            if need_voice or need_caption:
                inherited_voice, spoken = await read_formal_clip_defaults(
                    session,
                    project_id=project_id,
                    shot_id=shot.id,
                    video_id=UUID(str(old["artifact_id"])),
                    composite_id=shot.formal_composite_artifact_id,
                )
                if need_voice:
                    if inherited_voice is None and spoken != "":
                        raise _invalid("请先选择已有配音或明确静音，再保存混合剪辑")
                    clip["audio_id"] = inherited_voice
                if need_caption:
                    if spoken is None:
                        raise _invalid("请明确本段字幕，再保存混合剪辑")
                    clip["subtitle"] = spoken
            for key in (
                "shot_id",
                "artifact_id",
                "scene_id",
                "episode_id",
                "scene_number",
                "shot_number",
                "episode_number",
            ):
                clip.pop(key, None)
        for legacy, key in (
            ("trim_start_seconds", "source_in_seconds"),
            ("trim_end_seconds", "source_out_seconds"),
        ):
            if legacy in clip:
                value = clip.pop(legacy)
                clip.setdefault(key, value)
        if clip.get("transition") is not None:
            kind, seconds = clip_transition(clip["transition"])
            clip["transition"] = {"kind": kind, "duration_seconds": seconds}
        if clip.get("audio_id") is not None:
            if clip.get("audio_source"):
                raise _invalid("select one clip audio source")
            try:
                audio_id = UUID(str(clip["audio_id"]))
            except ValueError as exc:
                raise _invalid("invalid private audio") from exc
            audio = await read_media_source(session, artifact_id=audio_id)
            if (
                audio is None
                or audio.project_id != project_id
                or audio.artifact_type != "audio"
                or audio.storage_state != "available"
            ):
                raise _invalid("所选配音在当前项目不可用")
        clips.append(clip)
    return {**timeline, "clips": clips}


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
    document = parse_schema2(
        await _preserve_clip_edits(session, project_id, timeline, previous_timeline)
    )
    previous_by_clip = _previous_snapshots(previous_timeline)
    original_clips = (previous_timeline or {}).get("clips")
    previous_legacy = (
        {item.get("id"): item for item in original_clips if isinstance(item, dict)}
        if isinstance(original_clips, list)
        and (previous_timeline or {}).get("schema_version", 1) == 1
        else {}
    )
    stored: list[dict[str, Any]] = []
    for index, clip in enumerate(document.clips):
        payload = clip.model_dump(mode="json", exclude_unset=True)
        old = previous_by_clip.get(clip.id, {})
        for source, media_kind, field in (
            (clip.source, "video", "selection_snapshot"),
            (clip.audio_source, "audio", "audio_selection_snapshot"),
        ):
            payload.pop(field, None)
            if source is None:
                continue
            previous = old.get(field)
            verified = await _verify_source(
                session,
                project_id=project_id,
                source=source,
                index=index,
                episode_id=episode_id,
                media_kind=media_kind,
                previous=previous,
            )
            observed = await _observe_source(
                session,
                clip_id=clip.id,
                source=source,
                session_version=session_version or 1,
                media_artifact=verified,
            )
            if isinstance(previous, dict) and _same_observation(previous, observed):
                payload[field] = dict(previous)
            else:
                initial = previous.get("initial_source") if isinstance(previous, dict) else None
                old_clip = previous_legacy.get(clip.id, {})
                if (
                    field == "selection_snapshot"
                    and old_clip.get("shot_id")
                    and old_clip.get("artifact_id")
                ):
                    initial = {
                        "kind": "shot_formal",
                        "shot_id": old_clip["shot_id"],
                        "artifact_id": old_clip["artifact_id"],
                    }
                payload[field] = {
                    **observed,
                    "initial_source": initial or source.model_dump(mode="json", exclude_none=True),
                }
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
        if isinstance(clip_id, str):
            indexed[clip_id] = raw
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
