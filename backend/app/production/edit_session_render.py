"""Dispatch and execute an edit-session render (I9-02).

Dispatch freezes one immutable session version into a NodeRun snapshot; execution
turns that snapshot into MP4 + SRT and binds the rendered artifact back to the
export receipt. The Worker path is deliberately narrow: it reads only the frozen
snapshot, never re-reads the live timeline, so a later edit cannot change what a
queued render will produce.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import get_settings
from app.delivery.models import Export
from app.editing.models import EditSession
from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.run_state import ExecuteNodeResult
from app.production.edit_render_plan import build_render_plan
from app.production.service import GraphService
from app.production.session_exports import timeline_hash
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore

EDIT_RENDER_TEMPLATE = "edit-session-render-v1"
EDIT_RENDER_NODE_KEY = "edit_session_render"


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def create_edit_session_render(
    session: AsyncSession,
    *,
    project_id: UUID,
    session_id: UUID,
    export_id: UUID,
    actor_id: UUID,
) -> NodeRun:
    """Queue one render run for the export's frozen timeline version."""
    from app.production.models import ProductionGraph

    # The render graph and attempt sequence are shared by the project's exports.
    await session.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    export = await session.scalar(
        select(Export)
        .where(Export.id == export_id, Export.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if export is None:
        raise NotFoundError("export not found")
    if export.edit_session_id != session_id:
        raise ValidationAppError(
            "export does not belong to this edit session",
            details={"code": "RENDER_EXPORT_MISMATCH"},
        )
    if export.render_node_run_id is not None:
        prior = await session.get(NodeRun, export.render_node_run_id)
        if prior is None or prior.project_id != project_id:
            raise ConflictError("bound render run is unavailable")
        return prior
    edit_session = await session.scalar(
        select(EditSession).where(
            EditSession.id == session_id, EditSession.project_id == project_id
        )
    )
    if edit_session is None:
        raise NotFoundError("edit session not found")
    if export.timeline_version != edit_session.version:
        # Never render a version the receipt did not freeze.
        raise ConflictError(
            "export froze a different timeline version",
            details={
                "code": "RENDER_VERSION_STALE",
                "export_timeline_version": export.timeline_version,
                "session_version": edit_session.version,
            },
        )
    document: dict[str, Any] = dict(edit_session.timeline or {})
    if export.timeline_hash and export.timeline_hash != timeline_hash(document):
        raise ConflictError(
            "frozen timeline hash no longer matches the session",
            details={"code": "RENDER_HASH_MISMATCH"},
        )
    plan = build_render_plan(
        edit_session_id=edit_session.id,
        timeline_version=edit_session.version,
        timeline_hash=export.timeline_hash or timeline_hash(document),
        episode_id=edit_session.episode_id,
        document=document,
    )
    if export.format == "srt" and not plan.srt_bytes:
        raise ValidationAppError(
            "the requested subtitle export contains no captions",
            details={"code": "EXPORT_SUBTITLES_EMPTY"},
        )
    instructions = [asdict(item) for item in plan.instructions]
    sources = await _render_sources(session, project_id, instructions)
    for clip in document["clips"] if document.get("schema_version") == 2 else []:
        for field in ("selection_snapshot", "audio_selection_snapshot"):
            saved = clip.get(field)
            if not saved or (field == "audio_selection_snapshot" and clip.get("muted")):
                continue
            artifact = sources.get(UUID(saved["artifact_id"]))
            if artifact is None or artifact.content_hash != saved.get("artifact_hash"):
                raise ConflictError(
                    "saved media has changed", details={"code": "RENDER_INPUT_HASH_MISMATCH"}
                )
    snapshot: dict[str, Any] = {
        "source_commit": get_settings().source_commit,
        "node_key": EDIT_RENDER_NODE_KEY,
        "edit_session_id": str(edit_session.id),
        "export_id": str(export.id),
        "timeline_version": plan.timeline_version,
        "timeline_hash": plan.timeline_hash,
        "instructions": instructions,
        "source_hashes": {str(key): row.content_hash for key, row in sources.items()},
    }
    input_hash = _snapshot_hash(snapshot)
    graphs = GraphService(session)
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project_id,
            ProductionGraph.scope_type == "project",
            ProductionGraph.scope_entity_id == project_id,
            ProductionGraph.template_key == EDIT_RENDER_TEMPLATE,
        )
    )
    if graph is None or graph.current_version_id is None:
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="project",
            scope_entity_id=project_id,
            template_key=EDIT_RENDER_TEMPLATE,
            created_by=actor_id,
            definition={
                "nodes": [
                    {
                        "key": EDIT_RENDER_NODE_KEY,
                        "type": "export",
                        "display_name": "Edit Session Timeline Render",
                    }
                ],
                "edges": [],
            },
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    if materialized.version.status == "draft":
        await graphs.publish(version_id=materialized.version.id, published_by=actor_id)
    node = materialized.nodes[EDIT_RENDER_NODE_KEY]

    existing = await session.scalar(
        select(NodeRun)
        .where(
            NodeRun.project_id == project_id,
            NodeRun.graph_node_id == node.id,
            NodeRun.input_hash == input_hash,
        )
        .order_by(NodeRun.attempt_no.desc())
        .limit(1)
    )
    if existing is not None:
        # One render per frozen snapshot; a retry observes the same identity.
        return existing
    attempt = (
        int(
            await session.scalar(
                select(NodeRun.attempt_no)
                .where(NodeRun.graph_node_id == node.id)
                .order_by(NodeRun.attempt_no.desc())
                .limit(1)
            )
            or 0
        )
        + 1
    )
    run = NodeRun(
        project_id=project_id,
        graph_version_id=materialized.version.id,
        graph_node_id=node.id,
        attempt_no=attempt,
        idempotency_key=f"edit-render:{export.id}:{plan.timeline_hash[:16]}",
        input_hash=input_hash,
        status="queued",
        input_snapshot=snapshot,
        created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    export.render_node_run_id = run.id
    await session.flush()
    return run


async def _render_sources(
    session: AsyncSession, project_id: UUID, instructions: list[dict[str, Any]]
) -> dict[UUID, Artifact]:
    expected = [
        (UUID(str(item[field])), kind)
        for item in instructions
        for field, kind in (("video_artifact_id", "video"), ("audio_artifact_id", "audio"))
        if item.get(field)
    ]
    ids = {key for key, _ in expected}
    sources = {
        row.id: row
        for row in await session.scalars(
            select(Artifact).where(
                Artifact.id.in_(ids),
                Artifact.project_id == project_id,
                Artifact.deleted_at.is_(None),
                Artifact.storage_state == "available",
            )
        )
    }
    for key, kind in expected:
        if key not in sources or sources[key].artifact_type != kind:
            raise ValidationAppError(
                "render source is unavailable",
                details={"code": "RENDER_INPUT_UNAVAILABLE", "artifact_id": str(key)},
            )
    return sources


async def _stage_source(
    store: ObjectStore, artifact: Artifact, path: Path, expected_hash: str
) -> None:
    digest = hashlib.sha256()
    size = 0
    with path.open("xb") as output:
        async for chunk in store.iter_bytes(object_key=artifact.object_key):
            size += len(chunk)
            if size > artifact.byte_size:
                break
            digest.update(chunk)
            output.write(chunk)
    if size != artifact.byte_size or digest.hexdigest() != expected_hash:
        raise ValidationAppError(
            "render source differs from the frozen bytes",
            details={"code": "RENDER_INPUT_HASH_MISMATCH", "artifact_id": str(artifact.id)},
        )


async def execute_edit_session_render(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    obj_store: Any,
) -> ExecuteNodeResult:
    """Render the frozen snapshot into MP4 + SRT and bind it to the export."""
    from app.production.timeline_renderer import (
        TimelineRenderClip,
        TimelineRenderError,
        render_timeline,
    )

    snapshot = dict(run.input_snapshot or {})
    raw_instructions = snapshot.get("instructions")
    if not isinstance(raw_instructions, list) or not raw_instructions:
        raise ValidationAppError(
            "render run has no frozen instructions",
            details={"code": "RENDER_SNAPSHOT_INVALID"},
        )
    export_id = snapshot.get("export_id")
    if not isinstance(export_id, str):
        raise ValidationAppError(
            "render run is not bound to an export",
            details={"code": "RENDER_SNAPSHOT_INVALID"},
        )
    export = await session.scalar(
        select(Export).where(Export.id == UUID(export_id), Export.project_id == run.project_id)
    )
    if export is None:
        raise NotFoundError("export not found")

    artifacts = await _render_sources(session, run.project_id, raw_instructions)
    hashes = snapshot.get("source_hashes")
    if hashes is not None and not isinstance(hashes, dict):
        raise ValidationAppError(
            "render input hashes are invalid", details={"code": "RENDER_SNAPSHOT_INVALID"}
        )
    with tempfile.TemporaryDirectory(prefix="edit-render-") as temp:
        directory = Path(temp)
        paths: dict[str, Path] = {}
        for artifact in artifacts.values():
            key = str(artifact.id)
            path = directory / key
            expected_hash = artifact.content_hash if hashes is None else hashes.get(key)
            if expected_hash != artifact.content_hash:
                raise ValidationAppError(
                    "render source metadata changed",
                    details={"code": "RENDER_INPUT_HASH_MISMATCH", "artifact_id": key},
                )
            await _stage_source(obj_store, artifact, path, expected_hash)
            paths[key] = path
        clips = [
            TimelineRenderClip(
                **item,
                video_path=paths[item["video_artifact_id"]],
                audio_path=paths.get(item.get("audio_artifact_id", "")),
            )
            for item in raw_instructions
        ]
        try:
            rendered = await render_timeline(
                clips,
                lineage=str(snapshot.get("timeline_hash") or run.input_hash),
                output_path=directory / "edit-session.mp4",
            )
        except TimelineRenderError as exc:
            raise ValidationAppError(
                "the frozen timeline could not be rendered",
                details={"code": "RENDER_FAILED"},
            ) from exc
        prefix = f"projects/{run.project_id}/edit-exports/{export.id}/{uuid4()}"
        mp4_key = f"{prefix}.mp4"
        stored = await obj_store.put_file(
            object_key=mp4_key, path=rendered.output_path, mime_type="video/mp4"
        )
        subtitle_key: str | None = None
        subtitle_stored = None
        if rendered.subtitle_data:
            subtitle_key = f"{prefix}.srt"
            subtitle_stored = await obj_store.put_bytes(
                object_key=subtitle_key,
                data=rendered.subtitle_data,
                mime_type="application/x-subrip",
            )

    mp4 = Artifact(
        project_id=run.project_id,
        artifact_type="video",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type="video/mp4",
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
        duration_seconds=rendered.summary.get("rendered_duration_seconds"),
    )
    session.add(mp4)
    await session.flush()
    deliverable = mp4
    subtitle_artifact_id: str | None = None
    if subtitle_stored is not None:
        subtitle = Artifact(
            project_id=run.project_id,
            artifact_type="subtitle",
            storage_state="available",
            object_key=subtitle_stored.object_key,
            content_hash=subtitle_stored.content_hash,
            mime_type="application/x-subrip",
            byte_size=subtitle_stored.byte_size,
            produced_by_run_id=run.id,
        )
        session.add(subtitle)
        await session.flush()
        subtitle_artifact_id = str(subtitle.id)
        if export.format == "srt":
            deliverable = subtitle
    elif export.format == "srt":
        raise ValidationAppError(
            "the renderer produced no subtitles",
            details={"code": "EXPORT_SUBTITLES_EMPTY"},
        )

    export.result_artifact_id = deliverable.id
    export.render_node_run_id = run.id
    export.status = "completed"
    export.completed_at = datetime.now(UTC)
    export.manifest = {
        **(export.manifest or {}),
        "render_node_run_id": str(run.id),
        "rendered_artifact_id": str(mp4.id),
        "subtitle_artifact_id": subtitle_artifact_id,
        "render_summary": rendered.summary,
    }
    run.result_artifact_id = mp4.id
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=mp4.id,
        object_key=mp4.object_key,
        content_hash=mp4.content_hash,
        byte_size=mp4.byte_size,
        identity_status=None,
        provider_operation_id=None,
        node_type=node.node_type,
    )


__all__ = [
    "EDIT_RENDER_NODE_KEY",
    "EDIT_RENDER_TEMPLATE",
    "create_edit_session_render",
    "execute_edit_session_render",
]
