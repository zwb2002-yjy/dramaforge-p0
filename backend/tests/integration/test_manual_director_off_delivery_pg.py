"""D8 offline MANUAL path: empty project to real MP4/SRT with no Director runtime.

Source image/video results are explicit local acceptance fixtures recorded as
canonical NodeRun/ProviderOperation/Artifact facts. No network Provider or text
model is called. The Final Film itself is rendered by the real FFmpeg path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.access.models import ProjectCreativeProfile, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.assets.script_import import import_script
from app.delivery.models import ExportItem, ReviewAnnotation
from app.director.runtime.models import DirectorRuntimeControl, DirectorRuntimeWakeup
from app.director.turn_models import DirectorTurn
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.editing.timeline_builder import build_edit_session_from_shots
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production import timeline_renderer
from app.production.final_film import (
    execute_final_film_node_run,
    get_final_film_status,
    queue_final_film_render,
)
from app.production.formal_selection import set_formal_keyframe, set_formal_video
from app.production.repair_service import RepairService
from app.production.service import GraphService
from app.runtime.scheduler import NodeRunScheduler
from app.shared.db import set_rls_context
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

MANUAL_SCRIPT = """# Episode 1 - Manual delivery

## Scene 1 - Studio / night
One deliberately small offline acceptance scene.

### Shot 1 - medium
Visual: A performer holds still under a blue light.
Dialogue: 导演关闭后，手动流程仍然完成。
Camera: static
"""


async def _fake_enqueue(self: NodeRunScheduler, node_run_id: object) -> str:
    _ = self
    return f"offline-job-{node_run_id}"


async def _media_bytes(tmp_path: Path) -> tuple[bytes, bytes, bytes]:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "Real FFmpeg is required for D8 MANUAL delivery verification"
    image_buffer = BytesIO()
    Image.new("RGB", (320, 240), color=(20, 60, 180)).save(image_buffer, format="PNG")
    video_path = tmp_path / "manual-source.mp4"
    voice_path = tmp_path / "manual-voice.wav"
    await timeline_renderer._run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=20:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video_path),
        ],
        timeout=30,
    )
    await timeline_renderer._run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=22050",
            "-t",
            "3",
            "-c:a",
            "pcm_s16le",
            str(voice_path),
        ],
        timeout=30,
    )
    return image_buffer.getvalue(), video_path.read_bytes(), voice_path.read_bytes()


async def _store_artifact(
    *,
    project_id: UUID,
    object_key: str,
    data: bytes,
    artifact_type: str,
    mime_type: str,
    produced_by_run_id: UUID | None = None,
    duration_seconds: Decimal | None = None,
) -> Artifact:
    stored = await get_object_store().put_bytes(
        object_key=object_key, data=data, mime_type=mime_type,
    )
    return Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        width=320 if artifact_type == "image" else None,
        height=240 if artifact_type == "image" else None,
        duration_seconds=duration_seconds,
        produced_by_run_id=produced_by_run_id,
    )


async def _persist_source_result(
    session,
    *,
    project_id: UUID,
    actor_id: UUID,
    graph_version_id: UUID,
    node: GraphNode,
    shot_id: UUID,
    stage: str,
    data: bytes,
    artifact_type: str,
    mime_type: str,
) -> tuple[NodeRun, Artifact]:
    digest = hashlib.sha256(data).hexdigest()
    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"manual-offline:{stage}:{shot_id}",
        input_hash=hashlib.sha256(f"{stage}:{shot_id}".encode()).hexdigest(),
        status="running",
        input_snapshot={
            "shot_id": str(shot_id),
            "stage": stage,
            "node_key": node.node_key,
            "execution_path": "offline-acceptance-fixture-v1",
        },
        output_summary={"status": "completed", "offline_fixture": True},
        created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    artifact = await _store_artifact(
        project_id=project_id,
        object_key=f"projects/{project_id}/offline/{stage}-{digest[:12]}.{artifact_type}",
        data=data,
        artifact_type=artifact_type,
        mime_type=mime_type,
        produced_by_run_id=run.id,
        duration_seconds=Decimal("3.000") if artifact_type == "video" else None,
    )
    session.add(artifact)
    await session.flush()
    run.result_artifact_id = artifact.id
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    node.latest_successful_run_id = run.id
    session.add(ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="image.generate" if artifact_type == "image" else "video.generate",
        actual_provider="offline_fixture",
        actual_model="offline-fixture-v1",
        protocol_profile="offline_fixture_v1",
        request_fingerprint=run.input_hash,
        execution_path_version="offline-fixture-v1",
        status="succeeded",
        request_summary={"stage": stage, "network": False},
        response_summary={"content_hash": artifact.content_hash},
        submitted_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        provider_cost=Decimal("0"),
        currency="USD",
    ))
    await session.flush()
    return run, artifact


async def _render_final(session, *, project_id: UUID, edit: EditSession, actor_id: UUID, key: str):
    queued = await queue_final_film_render(
        session,
        project_id=project_id,
        edit_session_id=edit.id,
        expected_timeline_version=edit.version,
        actor_id=actor_id,
        idempotency_key=key,
        name="MANUAL director-off delivery",
    )
    run = await session.get(NodeRun, queued.node_run_id)
    assert run is not None
    run.status = "running"
    await session.commit()
    node = await session.get(GraphNode, run.graph_node_id)
    assert node is not None
    await execute_final_film_node_run(
        session, run=run, node=node, obj_store=get_object_store(),
    )
    return await get_final_film_status(
        session, project_id=project_id, node_run_id=run.id,
    )


@pytest.mark.asyncio
async def test_empty_manual_project_reaches_real_mp4_srt_with_director_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbname = f"dramaforge_d8_manual_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    reset_object_store_for_tests()
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        image_bytes, video_bytes, voice_bytes = await _media_bytes(tmp_path)
        settings = timeline_renderer.get_settings().model_copy(update={"app_env": "development"})
        monkeypatch.setattr(timeline_renderer, "get_settings", lambda: settings)
        monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)

        async with factory() as session:
            actor = User(
                email=f"d8-manual-{uuid4().hex}@example.com",
                display_name="D8 MANUAL owner",
                password_hash=hash_password("password123"),
            )
            session.add(actor)
            await session.flush()
            workspace = Workspace(owner_user_id=actor.id, name="D8 MANUAL workspace")
            session.add(workspace)
            await session.flush()
            await set_rls_context(session, user_id=actor.id, workspace_id=workspace.id)
            project = await ProjectService(session).create_project(
                workspace_id=workspace.id,
                name="D8 empty MANUAL project",
                aspect_ratio="16:9",
                actor=actor,
                start_type="FREE",
                director_autonomy="MANUAL",
            )
            await session.commit()
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=workspace.id,
                project_id=project.id,
            )
            profile = await session.scalar(select(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project.id,
            ))
            assert profile is not None and profile.director_autonomy == "MANUAL"
            for model in (Episode, Scene, Shot, NodeRun, ProviderOperation, DirectorTurn):
                assert await session.scalar(select(func.count()).select_from(model)) == 0

            imported = await import_script(
                session,
                project_id=project.id,
                actor_id=actor.id,
                filename="manual-director-off.md",
                text=MANUAL_SCRIPT,
                actor=actor,
            )
            assert imported.scene_count == 1 and imported.shot_count == 1
            shot = await session.scalar(select(Shot).where(Shot.project_id == project.id))
            assert shot is not None

            graph = await GraphService(session).create_graph(
                project_id=project.id,
                scope_type="shot",
                scope_entity_id=shot.id,
                template_key="manual-offline-production-v1",
                created_by=actor.id,
                definition={
                    "nodes": [
                        {"key": "keyframe", "type": "keyframe"},
                        {"key": "video", "type": "video"},
                        {"key": "composite", "type": "composite"},
                    ],
                    "edges": [],
                },
            )
            assert graph.current_version_id is not None
            await GraphService(session).materialize_definition(version_id=graph.current_version_id)
            nodes = list((await session.scalars(select(GraphNode).where(
                GraphNode.graph_version_id == graph.current_version_id,
            ))).all())
            by_key = {node.node_key: node for node in nodes}
            _keyframe_run, keyframe = await _persist_source_result(
                session,
                project_id=project.id,
                actor_id=actor.id,
                graph_version_id=graph.current_version_id,
                node=by_key["keyframe"],
                shot_id=shot.id,
                stage="image_keyframe",
                data=image_bytes,
                artifact_type="image",
                mime_type="image/png",
            )
            await set_formal_keyframe(
                session,
                project_id=project.id,
                shot_id=shot.id,
                artifact_id=keyframe.id,
                expected_shot_version=shot.version,
            )
            _video_run, video = await _persist_source_result(
                session,
                project_id=project.id,
                actor_id=actor.id,
                graph_version_id=graph.current_version_id,
                node=by_key["video"],
                shot_id=shot.id,
                stage="video",
                data=video_bytes,
                artifact_type="video",
                mime_type="video/mp4",
            )
            await set_formal_video(
                session,
                project_id=project.id,
                shot_id=shot.id,
                artifact_id=video.id,
                expected_shot_version=shot.version,
            )
            voice = await _store_artifact(
                project_id=project.id,
                object_key=f"projects/{project.id}/offline/manual-voice.wav",
                data=voice_bytes,
                artifact_type="audio",
                mime_type="audio/wav",
                duration_seconds=Decimal("3.000"),
            )
            session.add(voice)
            subtitle = await _store_artifact(
                project_id=project.id,
                object_key=f"projects/{project.id}/offline/manual-source.srt",
                data=(
                    "1\n00:00:00,000 --> 00:00:02,500\n"
                    "导演关闭后，手动流程仍然完成。\n"
                ).encode(),
                artifact_type="subtitle",
                mime_type="application/x-subrip",
            )
            session.add(subtitle)
            await session.flush()
            composite_run = NodeRun(
                project_id=project.id,
                graph_version_id=graph.current_version_id,
                graph_node_id=by_key["composite"].id,
                attempt_no=1,
                idempotency_key=f"manual-offline:composite:{shot.id}",
                input_hash=hashlib.sha256(f"composite:{shot.id}".encode()).hexdigest(),
                status="running",
                input_snapshot={
                    "shot_id": str(shot.id),
                    "node_key": "composite",
                    "execution_branch": "formal",
                    "media_inputs": {
                        "video": {
                            "artifact_id": str(video.id),
                            "content_hash": video.content_hash,
                        },
                        "voice": {"artifact_id": str(voice.id)},
                        "subtitle": {"artifact_id": str(subtitle.id)},
                    },
                },
                output_summary={"status": "completed"},
                created_by=actor.id,
            )
            session.add(composite_run)
            await session.flush()
            composite = await _store_artifact(
                project_id=project.id,
                object_key=f"projects/{project.id}/offline/composite-lineage.mp4",
                data=b"offline-composite-lineage-v1",
                artifact_type="video",
                mime_type="video/mp4",
                produced_by_run_id=composite_run.id,
                duration_seconds=Decimal("3.000"),
            )
            session.add(composite)
            await session.flush()
            composite_run.result_artifact_id = composite.id
            composite_run.status = "completed"
            composite_run.finished_at = datetime.now(UTC)
            by_key["composite"].latest_successful_run_id = composite_run.id
            shot.formal_composite_artifact_id = composite.id

            annotation = ReviewAnnotation(
                project_id=project.id,
                shot_id=shot.id,
                created_by=actor.id,
                target_kind="video_time",
                time_start=Decimal("0.5"),
                time_end=Decimal("1.0"),
                note="Manual review confirms the held pose.",
                severity="note",
                status="open",
            )
            session.add(annotation)
            await session.flush()
            repair = await RepairService(session).build_repair_plan(
                project=project, shot_id=shot.id,
            )
            assert repair.annotation_count == 1

            built = await build_edit_session_from_shots(
                session,
                project_id=project.id,
                user_id=actor.id,
                shot_ids=[shot.id],
                name="MANUAL timeline",
            )
            edit = await session.get(EditSession, UUID(str(built["session_id"])))
            assert edit is not None
            clips = [dict(clip) for clip in edit.timeline["clips"]]
            clips[0].update({
                "duration_seconds": 2.5,
                "source_in_seconds": 0.25,
                "subtitle": "导演关闭后，手动流程仍然完成。",
            })
            lineage_before = dict(edit.production_lineage)
            edit = await EditingAdapter(session).save_timeline(
                project_id=project.id,
                session_id=edit.id,
                timeline={"clips": clips, "metadata": {"manual": True}},
            )
            assert edit.version == 2 and edit.production_lineage == lineage_before
            source_operation_ids = set((await session.scalars(select(ProviderOperation.id).where(
                ProviderOperation.operation_kind.in_(("image.generate", "video.generate")),
            ))).all())
            assert len(source_operation_ids) == 2
            await session.commit()

            first = await _render_final(
                session,
                project_id=project.id,
                edit=edit,
                actor_id=actor.id,
                key="manual-offline:final:v2",
            )
            assert first.status == "completed" and first.result is not None
            result = first.result
            assert result.subtitle_artifact_id is not None
            mp4_artifact = await session.get(Artifact, result.artifact_id)
            srt_artifact = await session.get(Artifact, result.subtitle_artifact_id)
            assert mp4_artifact is not None and srt_artifact is not None
            mp4_data = await get_object_store().get_bytes(object_key=mp4_artifact.object_key)
            srt_data = await get_object_store().get_bytes(object_key=srt_artifact.object_key)
            mp4_path = tmp_path / "manual-director-off.mp4"
            srt_path = tmp_path / "manual-director-off.srt"
            mp4_path.write_bytes(mp4_data)
            srt_path.write_bytes(srt_data)
            probe = await timeline_renderer._probe(mp4_path)
            streams = probe["streams"]
            assert {item["codec_name"] for item in streams} >= {"h264", "aac"}
            assert abs(float(probe["format"]["duration"]) - 2.5) <= 0.15
            assert "导演关闭后" in srt_data.decode("utf-8")
            items = list((await session.scalars(select(ExportItem).where(
                ExportItem.export_id == result.export_id,
            ))).all())
            assert "final_subtitle" in {item.role for item in items}
            assert any(item.role == "shot_composite" for item in items)

            clips[0]["subtitle"] = "字幕修改后重新导出。"
            edit = await EditingAdapter(session).save_timeline(
                project_id=project.id,
                session_id=edit.id,
                timeline={"clips": clips, "metadata": {"manual": True, "revision": 2}},
            )
            await session.commit()
            second = await _render_final(
                session,
                project_id=project.id,
                edit=edit,
                actor_id=actor.id,
                key="manual-offline:final:v3",
            )
            assert second.status == "completed" and second.result is not None
            assert second.result.artifact_id != result.artifact_id
            after_source_ids = set((await session.scalars(select(ProviderOperation.id).where(
                ProviderOperation.operation_kind.in_(("image.generate", "video.generate")),
            ))).all())
            assert after_source_ids == source_operation_ids
            assert shot.formal_keyframe_artifact_id == keyframe.id
            assert shot.formal_video_artifact_id == video.id
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
            assert await session.scalar(
                select(func.count()).select_from(DirectorRuntimeControl)
            ) == 0
            assert await session.scalar(
                select(func.count()).select_from(DirectorRuntimeWakeup)
            ) == 0

            evidence_dir_raw = os.environ.get("D8_EVIDENCE_DIR")
            if evidence_dir_raw:
                evidence_dir = Path(evidence_dir_raw)
                evidence_dir.mkdir(parents=True, exist_ok=True)
                delivered_mp4 = evidence_dir / "manual-director-off.mp4"
                delivered_srt = evidence_dir / "manual-director-off.srt"
                delivered_mp4.write_bytes(mp4_data)
                delivered_srt.write_bytes(srt_data)
                source_sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=Path(__file__).resolve().parents[3],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                evidence = {
                    "status": "LOCAL_VERIFIED",
                    "source_sha": source_sha,
                    "working_tree_dirty": True,
                    "network_provider_calls": 0,
                    "director_turn_count": 0,
                    "director_runtime_control_count": 0,
                    "director_runtime_wakeup_count": 0,
                    "project_id": str(project.id),
                    "edit_session_id": str(edit.id),
                    "timeline_versions": [2, 3],
                    "first_node_run_id": str(first.node_run_id),
                    "first_export_id": str(result.export_id),
                    "mp4_artifact_id": str(result.artifact_id),
                    "srt_artifact_id": str(result.subtitle_artifact_id),
                    "mp4_sha256": hashlib.sha256(mp4_data).hexdigest(),
                    "srt_sha256": hashlib.sha256(srt_data).hexdigest(),
                    "duration_seconds": probe["format"]["duration"],
                    "codecs": sorted({item["codec_name"] for item in streams}),
                    "source_image_video_operation_delta_after_rerender": 0,
                }
                (evidence_dir / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
    finally:
        await engine.dispose()
        reset_object_store_for_tests()
        await _drop_database(dbname)
