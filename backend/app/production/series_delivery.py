"""Read current episode deliveries from the saved cut, completed render and export items."""

from collections import defaultdict
from contextlib import suppress
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Episode
from app.contracts.delivery_verification import DeliveryPackage
from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun
from app.production.delivery_graph import EDIT_RENDER_NODE, FINAL_FILM_FORMAT, FINAL_FILM_NODE
from app.production.session_exports import timeline_hash


class EpisodePackage(DeliveryPackage):
    episode_id: UUID
    episode_number: int


class SeriesDeliverySummary(BaseModel):
    planned_episodes: int | None
    ready_episodes: int
    missing_episode_ranges: list[tuple[int, int]]
    ready: bool
    episodes: list[EpisodePackage]


def _available(media: Artifact | None, project: UUID, kind: str, mime: str) -> bool:
    return bool(
        media
        and media.project_id == project
        and media.deleted_at is None
        and media.storage_state == "available"
        and media.byte_size > 0
        and media.content_hash
        and media.artifact_type == kind
        and media.mime_type == mime
    )


def _check_receipt[Package: DeliveryPackage](
    package: Package,
    edit: EditSession,
    export: Export,
    run: NodeRun,
    items: list[ExportItem],
    media: dict[str, Artifact],
) -> Package:
    snapshot = run.input_snapshot or {}
    manifest = export.manifest or {}
    raw_clips = (edit.timeline or {}).get("clips", [])
    clips = raw_clips if isinstance(raw_clips, list) else []
    final = export.format == FINAL_FILM_FORMAT
    blockers: list[str] = []
    if (
        run.status != "completed"
        or snapshot.get("edit_session_id") != str(edit.id)
        or snapshot.get("timeline_version") != edit.version
        or snapshot.get("timeline_hash") != package.timeline_hash
        or snapshot.get("node_key") != (FINAL_FILM_NODE if final else EDIT_RENDER_NODE)
        or (
            final
            and snapshot.get("episode_id")
            != (str(package.episode_id) if package.episode_id else None)
        )
        or (not final and snapshot.get("export_id") != str(export.id))
    ):
        blockers.append("DELIVERY_RENDER_MISMATCH")
    # Session exports record clip items in document order. Final films record
    # the ordered composites actually assembled, plus their subtitle item.
    if final:
        raw_refs = snapshot.get("formal_references")
        refs = raw_refs if isinstance(raw_refs, list) else []
        expected = [
            (str(ref.get("clip_id")), str(ref.get("composite_artifact_id")))
            for ref in refs
            if isinstance(ref, dict)
        ]
    else:
        expected = [
            (
                str(clip.get("id")),
                str(
                    (clip.get("selection_snapshot") or {}).get("artifact_id")
                    if clip.get("source")
                    else clip.get("artifact_id")
                ),
            )
            for clip in clips
            if isinstance(clip, dict)
        ]
    clip_items = [item for item in items if item.role != "final_subtitle"]
    actual = [(str(i.metadata_json.get("clip_id")), str(i.source_artifact_id)) for i in clip_items]
    if (
        not expected
        or len(expected) != len(clips)
        or actual != expected
        or any(
            i.ordinal != n or i.role != ("shot_composite" if final else "video")
            for n, i in enumerate(clip_items, start=1)
        )
        or (
            final
            and sorted(key for key, _ in expected)
            != sorted(str(c.get("id")) for c in clips if isinstance(c, dict))
        )
    ):
        blockers.append("DELIVERY_ITEMS_INCOMPLETE")
    video = media.get(str(run.result_artifact_id))
    subtitle = media.get(str(manifest.get("subtitle_artifact_id")))
    if not _available(video, edit.project_id, "video", "video/mp4") or (
        str(run.result_artifact_id)
        != str(manifest.get("artifact_id" if final else "rendered_artifact_id"))
    ):
        blockers.append("DELIVERY_MP4_MISSING")
        video = None
    if not _available(subtitle, edit.project_id, "subtitle", "application/x-subrip"):
        blockers.append("DELIVERY_SRT_MISSING")
        subtitle = None
    elif subtitle is not None:
        if final:
            subtitle_items = [i for i in items if i.role == "final_subtitle"]
            valid = (
                len(subtitle_items) == 1
                and subtitle_items[0].source_artifact_id == subtitle.id
                and subtitle.content_hash == manifest.get("subtitle_content_hash")
            )
        else:
            valid = subtitle.produced_by_run_id == run.id
        if not valid:
            blockers.append("DELIVERY_SRT_MISMATCH")
            subtitle = None
    primary = subtitle if export.format == "srt" else video
    if primary is not None and export.result_artifact_id != primary.id:
        blockers.append("DELIVERY_RESULT_MISMATCH")
    return package.model_copy(
        update={
            "export_id": export.id,
            "render_node_run_id": run.id,
            "blockers": blockers,
            "mp4_artifact_id": video.id if video else None,
            "srt_artifact_id": subtitle.id if subtitle else None,
            "srt_content_hash": subtitle.content_hash if subtitle else None,
            "mp4_content_hash": video.content_hash if video else None,
        }
    )


async def _receipt_facts(
    session: AsyncSession,
    project_id: UUID,
    edit_ids: list[UUID],
    *,
    lock: bool = False,
    export_id: UUID | None = None,
) -> tuple[
    dict[UUID, list[tuple[Export, NodeRun]]], dict[str, Artifact], dict[UUID, list[ExportItem]]
]:
    query = (
        select(Export, NodeRun)
        .join(NodeRun, NodeRun.id == Export.render_node_run_id)
        .join(
            EditSession,
            EditSession.id == Export.edit_session_id,
        )
        .where(
            Export.project_id == project_id,
            NodeRun.project_id == project_id,
            EditSession.project_id == project_id,
            EditSession.id.in_(edit_ids),
            Export.episode_id.is_not_distinct_from(EditSession.episode_id),
            Export.timeline_version == EditSession.version,
            Export.status == "completed",
            Export.result_artifact_id.is_not(None),
            Export.format.in_((FINAL_FILM_FORMAT, "mp4", "srt")),
        )
        .order_by(Export.completed_at.desc(), Export.id.desc())
    )
    if export_id is not None:
        query = query.where(Export.id == export_id)
    if lock:
        query = query.with_for_update(read=True, of=(Export, NodeRun))
    receipts = (await session.execute(query.execution_options(populate_existing=True))).all()
    by_edit: dict[UUID, list[tuple[Export, NodeRun]]] = defaultdict(list)
    artifact_ids: set[UUID] = set()
    for export, run in receipts:
        by_edit[export.edit_session_id].append((export, run))
        if run.result_artifact_id:
            artifact_ids.add(run.result_artifact_id)
        with suppress(ValueError):
            artifact_ids.add(UUID(str((export.manifest or {}).get("subtitle_artifact_id"))))
    media_query = (
        select(Artifact)
        .where(
            Artifact.id.in_(artifact_ids),
            Artifact.project_id == project_id,
        )
        .order_by(Artifact.id)
    )
    item_query = (
        select(ExportItem)
        .where(
            ExportItem.export_id.in_([e.id for e, _ in receipts]),
        )
        .order_by(ExportItem.export_id, ExportItem.ordinal)
    )
    if lock:
        media_query = media_query.with_for_update(read=True)
        item_query = item_query.with_for_update(read=True)
    media = {
        str(a.id): a
        for a in await session.scalars(media_query.execution_options(populate_existing=True))
    }
    items: dict[UUID, list[ExportItem]] = defaultdict(list)
    for item in await session.scalars(item_query.execution_options(populate_existing=True)):
        items[item.export_id].append(item)
    return by_edit, media, items


async def verify_delivery_target(
    session: AsyncSession,
    *,
    project_id: UUID,
    episode_id: UUID | None,
    edit_session_id: UUID | None,
    timeline_version: int | None,
    export_id: UUID | None,
) -> DeliveryPackage:
    """The caller holds the project lock until it persists the verification receipt."""
    package = DeliveryPackage(episode_id=episode_id, blockers=[])
    if episode_id is not None:
        number = await session.scalar(
            select(Episode.episode_number)
            .where(
                Episode.id == episode_id,
                Episode.project_id == project_id,
            )
            .with_for_update(read=True)
        )
        if number is None:
            package.blockers.append("DELIVERY_EPISODE_MISSING")
            return package
        package.episode_number = number
    query = select(EditSession).where(
        EditSession.project_id == project_id,
        EditSession.episode_id == episode_id,
    )
    if edit_session_id is not None:
        query = query.where(EditSession.id == edit_session_id)
    edit = await session.scalar(
        query.order_by(EditSession.updated_at.desc(), EditSession.id.desc())
        .limit(1)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if edit is None:
        package.blockers.append("DELIVERY_SESSION_MISSING")
        return package
    package.edit_session_id = edit.id
    package.timeline_version = edit.version
    package.timeline_hash = timeline_hash(edit.timeline)
    if timeline_version is not None and timeline_version != edit.version:
        package.blockers.append("DELIVERY_TIMELINE_CHANGED")
        return package
    receipts, media, items = await _receipt_facts(
        session,
        project_id,
        [edit.id],
        lock=True,
        export_id=export_id,
    )
    package.blockers.append("DELIVERY_CURRENT_EXPORT_MISSING")
    for export, run in receipts[edit.id]:
        if export.timeline_hash != package.timeline_hash:
            continue
        checked = _check_receipt(package, edit, export, run, items[export.id], media)
        if not checked.blockers:
            return checked
        if package.export_id is None:
            package = checked
    return package


async def series_delivery_summary(session: AsyncSession, project: Project) -> SeriesDeliverySummary:
    latest_edit_id = (
        select(EditSession.id)
        .where(EditSession.project_id == project.id, EditSession.episode_id == Episode.id)
        .order_by(EditSession.updated_at.desc(), EditSession.id.desc())
        .limit(1)
        .correlate(Episode)
        .scalar_subquery()
    )
    current = (
        await session.execute(
            select(Episode, EditSession)
            .outerjoin(EditSession, EditSession.id == latest_edit_id)
            .where(Episode.project_id == project.id)
            .order_by(Episode.episode_number)
        )
    ).all()
    episodes = [episode for episode, _ in current]
    edits = {episode.id: edit for episode, edit in current if edit is not None}
    by_edit, media, items = await _receipt_facts(
        session, project.id, [e.id for e in edits.values()]
    )
    packages: list[EpisodePackage] = []
    for episode in episodes:
        edit = edits.get(episode.id)
        package = EpisodePackage(
            episode_id=episode.id,
            episode_number=episode.episode_number,
            edit_session_id=edit.id if edit else None,
            timeline_version=edit.version if edit else None,
            timeline_hash=timeline_hash(edit.timeline) if edit else None,
            blockers=["DELIVERY_CURRENT_EXPORT_MISSING" if edit else "DELIVERY_SESSION_MISSING"],
        )
        if edit:
            for export, run in by_edit[edit.id]:
                if export.timeline_hash != package.timeline_hash:
                    continue
                checked = _check_receipt(package, edit, export, run, items[export.id], media)
                if package.export_id is None or not checked.blockers:
                    package = checked
                if not checked.blockers:
                    break
        packages.append(package)
    # Compact gaps keep large plan counts bounded by the actual episode rows.
    planned = project.planned_episode_count
    missing: list[tuple[int, int]] = []
    next_number = 1
    for episode in episodes:
        if planned and next_number <= planned and episode.episode_number > next_number:
            missing.append((next_number, min(episode.episode_number - 1, planned)))
        next_number = episode.episode_number + 1
    if planned and next_number <= planned:
        missing.append((next_number, planned))
    ready = sum(not item.blockers for item in packages)
    return SeriesDeliverySummary(
        planned_episodes=planned,
        ready_episodes=ready,
        missing_episode_ranges=missing,
        ready=bool(planned and not missing and ready == planned == len(episodes)),
        episodes=packages,
    )
