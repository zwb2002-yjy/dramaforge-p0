"""R6 ExportItem/Artifact transactional lineage and isolation on PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from app.delivery.models import ExportItem
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.final_film import (
    execute_final_film_node_run,
    get_final_film_status,
    queue_final_film_render,
)
from app.runtime.scheduler import NodeRunScheduler
from app.shared.db import set_rls_context
from app.storage.minio_store import get_object_store
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_final_film_timeline import _fake_enqueue, _seed_renderable_final_film


@pytest.mark.asyncio
async def test_final_subtitle_pair_is_owned_frozen_and_has_matching_bytes(
    pg_session, monkeypatch, record_property
):
    session = pg_session
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, shots, videos = await _seed_renderable_final_film(session)
    clips = [dict(clip) for clip in edit.timeline["clips"]]
    clips[0].pop("subtitle")
    shots[0].dialogue = "冻结的对白\nFrozen dialogue"
    edit.timeline = {"clips": clips, "metadata": {}}
    await session.commit()
    key = f"pg-srt:{uuid4().hex}"
    queued = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=edit.version,
        actor_id=user.id,
        idempotency_key=key,
        name="PG subtitle",
    )
    # Change live dialogue after dispatch; output must use the frozen default.
    shots[0].dialogue = "Do not leak new dialogue into the queued version"
    await session.commit()
    replay = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=edit.version,
        actor_id=user.id,
        idempotency_key=key,
        name="PG subtitle",
    )
    assert replay.node_run_id == queued.node_run_id
    run = await session.get(NodeRun, queued.node_run_id)
    run.status = "running"
    await session.commit()
    node = await session.get(GraphNode, run.graph_node_id)
    await execute_final_film_node_run(session, run=run, node=node, obj_store=get_object_store())
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as reader:
        await reader.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            reader, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id
        )
        job = await get_final_film_status(reader, project_id=project.id, node_run_id=run.id)
        result = job.result
        assert result is not None and result.subtitle_artifact_id is not None
        assert result.timeline_version == 1 and result.subtitle_cue_count == 1
        subtitle = await reader.get(Artifact, result.subtitle_artifact_id)
        assert subtitle.artifact_type == "subtitle" and subtitle.produced_by_run_id == run.id
        data = await get_object_store().get_bytes(object_key=subtitle.object_key)
        assert "冻结的对白\nFrozen dialogue" in data.decode("utf-8")
        assert b"Do not leak" not in data
        assert hashlib.sha256(data).hexdigest() == result.subtitle_content_hash
        item = await reader.scalar(
            select(ExportItem).where(
                ExportItem.export_id == result.export_id, ExportItem.role == "final_subtitle"
            )
        )
        assert (
            item.source_artifact_id == subtitle.id and item.metadata_json["timeline_version"] == 1
        )
        assert item.metadata_json["mp4_artifact_id"] == str(result.artifact_id)
        assert (
            list(
                (
                    await reader.execute(
                        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
                    )
                ).scalars()
            )[0].actual_provider
            == "local_ffmpeg"
        )
        record_property(
            "subtitle_delivery",
            json.dumps(
                {
                    "node_run_id": str(run.id),
                    "mp4_artifact_id": str(result.artifact_id),
                    "srt_artifact_id": str(subtitle.id),
                    "srt_sha256": subtitle.content_hash,
                    "export_id": str(result.export_id),
                    "timeline_version": result.timeline_version,
                    "source_media_calls": 0,
                },
                sort_keys=True,
            ),
        )
        subtitle_id = subtitle.id
    async with factory() as outsider:
        await outsider.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            outsider, user_id=user.id, workspace_id=project.workspace_id, project_id=uuid4()
        )
        assert await outsider.get(Artifact, subtitle_id) is None
    # Same Formal source, a new Timeline version with subtitles explicitly off.
    clips[0]["subtitle"] = ""
    clips[0]["subtitle_enabled"] = False
    clips[0]["muted"] = True
    edit.timeline = {"clips": clips, "metadata": {}}
    edit.version = 2
    await session.commit()
    second = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=2,
        actor_id=user.id,
        idempotency_key=f"pg-srt:{uuid4().hex}",
        name="Muted subtitle revision",
    )
    second_run = await session.get(NodeRun, second.node_run_id)
    second_run.status = "running"
    await session.commit()
    second_node = await session.get(GraphNode, second_run.graph_node_id)
    await execute_final_film_node_run(
        session, run=second_run, node=second_node, obj_store=get_object_store()
    )
    after = await get_final_film_status(session, project_id=project.id, node_run_id=second_run.id)
    assert after.result.subtitle_artifact_id is None and after.result.timeline_version == 2
    ops = list(
        (
            await session.execute(
                select(ProviderOperation)
                .join(NodeRun, NodeRun.id == ProviderOperation.node_run_id)
                .where(NodeRun.project_id == project.id)
            )
        ).scalars()
    )
    assert len(ops) == 2 and all(op.actual_provider == "local_ffmpeg" for op in ops)
    assert shots[0].formal_video_artifact_id == videos[0].id
    record_property(
        "rerender_evidence",
        json.dumps(
            {
                "timeline_versions": [1, 2],
                "local_render_operations": len(ops),
                "image_video_operation_delta": 0,
                "second_subtitle_artifact_id": None,
                "formal_source_unchanged": True,
            },
            sort_keys=True,
        ),
    )
