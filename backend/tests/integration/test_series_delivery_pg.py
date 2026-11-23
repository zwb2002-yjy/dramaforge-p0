"""Both render writers contribute exact episode receipts to the read-only series summary."""

from datetime import UTC, datetime

from app.assets.models import Asset, AssetVersion, AssetVersionReference, Episode
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.edit_session_render import (
    create_edit_session_render,
    execute_edit_session_render,
)
from app.production.final_film import execute_final_film_node_run, queue_final_film_render
from app.production.series_delivery import series_delivery_summary
from app.production.service import GraphService
from app.production.session_exports import SessionExports
from app.runtime.scheduler import NodeRunScheduler
from app.shared.db import set_rls_context
from app.storage.minio_store import get_object_store
from sqlalchemy import select, text
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark

from fixtures.final_film_seed import _fake_enqueue, _seed_renderable_final_film


async def test_current_series_needs_two_complete_matching_packages(pg_session, monkeypatch):
    db = pg_session
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _shots, videos = await _seed_renderable_final_film(db)
    project.work_type = "serial_comic"
    project.planned_episode_count = 2
    first = await db.scalar(select(Episode).where(Episode.project_id == project.id))
    edit.episode_id = first.id
    edit.timeline = {
        **edit.timeline,
        "clips": [
            {**clip, "subtitle": "Episode one", "subtitle_enabled": True}
            for clip in edit.timeline["clips"]
        ],
    }
    await db.commit()
    graphs = GraphService(db)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
        template_key="final-film-v1",
        created_by=user.id,
        definition={
            "nodes": [{"key": "final_film_assembly", "type": "export", "display_name": "Final"}],
            "edges": [],
        },
    )
    old_version = graph.current_version_id
    legacy = await graphs.materialize_definition(version_id=old_version)
    await graphs.publish(version_id=old_version, published_by=user.id)

    async def old_graph(*args, **kwargs):
        return graph, legacy.nodes["final_film_assembly"], legacy.version.version_number

    async def queue_first():
        return await queue_final_film_render(
            db,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=edit.version,
            actor_id=user.id,
            idempotency_key="episode-1",
            name="Episode one",
        )

    # Seed an authentic queued request in the former one-node graph.
    with monkeypatch.context() as older:
        older.setattr("app.production.final_film._ensure_final_graph", old_graph)
        queued = await queue_first()
    await db.commit()
    replay = await queue_first()
    assert replay.node_run_id == queued.node_run_id and graph.current_version_id != old_version
    run = await db.get(NodeRun, queued.node_run_id)
    run.status = "running"
    await db.commit()
    store = get_object_store()
    await execute_final_film_node_run(
        db, run=run, node=await db.get(GraphNode, run.graph_node_id), obj_store=store
    )
    await db.commit()
    partial = await series_delivery_summary(db, project)
    assert not partial.ready and partial.ready_episodes == 1, partial
    assert partial.missing_episode_ranges == [(2, 2)]
    first_package = partial.episodes[0]
    assert (await queue_first()).node_run_id == queued.node_run_id

    second = Episode(project_id=project.id, episode_number=2, title="Second")
    asset = Asset(project_id=project.id, kind="video", name="Shared location", version=1)
    db.add_all([asset, second])
    await db.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="video",
        name=asset.name,
        description="",
        status="formal",
        created_by=user.id,
    )
    db.add(version)
    await db.flush()
    asset.current_version_id = version.id
    db.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=videos[0].id,
            reference_role="primary",
            label="",
            sort_order=0,
        )
    )
    await db.flush()
    adapter = EditingAdapter(db)
    cut = await adapter.create_session(
        project_id=project.id,
        user_id=user.id,
        name="Second cut",
        episode_id=second.id,
    )
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=cut.id,
        expected_session_version=cut.version,
        timeline={
            "schema_version": 2,
            "clips": [
                {
                    "id": "two",
                    "order": 1,
                    "duration_seconds": 1,
                    "subtitle": "Episode two",
                    "source": {
                        "kind": "asset_version",
                        "asset_id": str(asset.id),
                        "asset_version_id": str(version.id),
                    },
                }
            ],
        },
    )
    receipt, _ = await SessionExports(db).create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        format="mp4",
    )
    task = await create_edit_session_render(
        db,
        project_id=project.id,
        session_id=saved.id,
        export_id=receipt.id,
        actor_id=user.id,
    )
    assert not (await series_delivery_summary(db, project)).ready
    await execute_edit_session_render(
        db,
        run=task,
        node=await db.get(GraphNode, task.graph_node_id),
        obj_store=store,
    )
    await db.commit()
    await db.execute(text("SET LOCAL ROLE dramaforge_app"))
    await set_rls_context(
        db, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id
    )
    complete = await series_delivery_summary(db, project)
    assert complete.ready and complete.ready_episodes == 2, complete
    assert complete.episodes[0] == first_package
    episode_two = complete.episodes[1]
    subtitle = await db.get(Artifact, episode_two.srt_artifact_id)
    assert await store.get_bytes(object_key=subtitle.object_key)
    subtitle.deleted_at = datetime.now(UTC)
    await db.flush()
    incomplete = await series_delivery_summary(db, project)
    assert not incomplete.ready and incomplete.episodes[1].blockers == ["DELIVERY_SRT_MISSING"]
    assert incomplete.episodes[0] == first_package
    await adapter.save_timeline(
        project_id=project.id,
        session_id=saved.id,
        expected_session_version=saved.version,
        timeline={**saved.timeline, "metadata": {"note": "New approved version"}},
    )
    revised = await series_delivery_summary(db, project)
    assert not revised.ready and revised.episodes[0] == first_package
    assert revised.episodes[1].blockers == ["DELIVERY_CURRENT_EXPORT_MISSING"]
