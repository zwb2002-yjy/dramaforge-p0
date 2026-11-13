"""Shared synthetic Final Film fixture; never part of the production runtime."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.editing.models import EditSession
from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.shot_pipeline import shot_pipeline_definition
from app.production.review_gate import record_human_decision
from app.production.service import GraphService
from app.runtime.scheduler import NodeRunScheduler
from app.shared.enums import ProjectStage
from app.shared.security import hash_password
from app.storage.minio_store import ObjectStore, get_object_store
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_project(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"final-{uuid4().hex}@example.com",
        display_name="Final Owner",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Final Film Project",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="9:16",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    return project, user


async def _seed_renderable_final_film(
    session: AsyncSession,
    *,
    shot_count: int = 1,
    canonical_graph: bool = False,
    object_store: ObjectStore | None = None,
) -> tuple[Project, User, EditSession, list[Shot], list[Artifact]]:
    project, user = await _seed_project(session)
    episode = Episode(project_id=project.id, episode_number=1, title="Episode 1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Rooftop",
        time_of_day="night",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    store = object_store if object_store is not None else get_object_store()
    shots: list[Shot] = []
    formal_videos: list[Artifact] = []
    timeline_clips: list[dict[str, object]] = []
    for index in range(shot_count):
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=index + 1,
            sort_order=index + 1,
            visual_description=f"Shot {index + 1}",
            dialogue=f"Line {index + 1}",
            duration_seconds=Decimal("5"),
        )
        session.add(shot)
        await session.flush()
        graph = await GraphService(session).create_graph(
            project_id=project.id,
            scope_type="shot",
            scope_entity_id=shot.id,
            template_key="shot-p0-v1",
            created_by=user.id,
            definition=shot_pipeline_definition()
            if canonical_graph
            else {
                "nodes": [
                    {"key": "video", "type": "video"},
                    {"key": "composite", "type": "composite"},
                    {"key": "video_drift_review", "type": "video_review"},
                ],
                "edges": [],
            },
        )
        assert graph.current_version_id is not None
        await GraphService(session).materialize_definition(version_id=graph.current_version_id)
        nodes = list(
            (
                await session.execute(
                    select(GraphNode).where(GraphNode.graph_version_id == graph.current_version_id)
                )
            )
            .scalars()
            .all()
        )
        composite_node = next(node for node in nodes if node.node_key == "composite")
        review_node = next(node for node in nodes if node.node_key == "video_drift_review")

        video_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/video-{index}.mp4",
            data=f"\x00\x00\x00\x18ftypmp42video-{index}".encode(),
            mime_type="video/mp4",
        )
        video_artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=video_stored.object_key,
            content_hash=video_stored.content_hash,
            mime_type="video/mp4",
            byte_size=video_stored.byte_size,
            duration_seconds=Decimal("5"),
        )
        session.add(video_artifact)
        await session.flush()
        voice_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/voice-{index}.wav",
            data=f"RIFFvoice-{index}".encode(),
            mime_type="audio/wav",
        )
        voice_artifact = Artifact(
            project_id=project.id,
            artifact_type="audio",
            storage_state="available",
            object_key=voice_stored.object_key,
            content_hash=voice_stored.content_hash,
            mime_type="audio/wav",
            byte_size=voice_stored.byte_size,
        )
        session.add(voice_artifact)
        subtitle_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/subtitle-{index}.srt",
            data=f"1\n00:00:00,000 --> 00:00:02,000\nLine {index + 1}\n".encode(),
            mime_type="application/x-subrip",
        )
        subtitle_artifact = Artifact(
            project_id=project.id,
            artifact_type="subtitle",
            storage_state="available",
            object_key=subtitle_stored.object_key,
            content_hash=subtitle_stored.content_hash,
            mime_type="application/x-subrip",
            byte_size=subtitle_stored.byte_size,
        )
        session.add(subtitle_artifact)
        await session.flush()
        composite_run = NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=composite_node.id,
            attempt_no=1,
            idempotency_key=f"formal-composite-{index}-{uuid4()}",
            input_hash="c" * 64,
            status="running",
            input_snapshot={
                "shot_id": str(shot.id),
                "node_key": "composite",
                "execution_branch": "formal",
                "media_inputs": {
                    "video": {
                        "artifact_id": str(video_artifact.id),
                        "content_hash": video_artifact.content_hash,
                    },
                    "voice": {
                        "artifact_id": str(voice_artifact.id),
                        "content_hash": voice_artifact.content_hash,
                    },
                    "subtitle": {
                        "artifact_id": str(subtitle_artifact.id),
                        "content_hash": subtitle_artifact.content_hash,
                    },
                },
            },
            created_by=user.id,
        )
        session.add(composite_run)
        await session.flush()
        composite_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/composite-{index}.mp4",
            data=f"\x00\x00\x00\x18ftypmp42composite-{index}".encode(),
            mime_type="video/mp4",
        )
        composite_artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=composite_stored.object_key,
            content_hash=composite_stored.content_hash,
            mime_type="video/mp4",
            byte_size=composite_stored.byte_size,
            duration_seconds=Decimal("5"),
            produced_by_run_id=composite_run.id,
        )
        session.add(composite_artifact)
        await session.flush()
        composite_run.result_artifact_id = composite_artifact.id
        composite_run.status = "completed"
        shot.formal_video_artifact_id = video_artifact.id
        shot.formal_composite_artifact_id = composite_artifact.id
        # Delivery requires a stored human decision for the exact clip Artifact,
        # so this fixture records one exactly like the product flow does.
        review_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/review-{index}.json",
            data=json.dumps(
                {"status": "needs_human", "artifact_id": str(video_artifact.id)}
            ).encode(),
            mime_type="application/json",
        )
        review_artifact = Artifact(
            project_id=project.id,
            artifact_type="document",
            storage_state="available",
            object_key=review_stored.object_key,
            content_hash=review_stored.content_hash,
            mime_type=review_stored.mime_type,
            byte_size=review_stored.byte_size,
        )
        session.add(review_artifact)
        await session.flush()
        review_run = NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=review_node.id,
            idempotency_key=f"video-drift-review-{uuid4().hex}",
            input_hash=uuid4().hex * 2,
            input_snapshot={
                "shot_id": str(shot.id),
                "node_key": "video_drift_review",
                "upstream_artifact_id": str(video_artifact.id),
            },
            output_summary={"status": "needs_human"},
            status="completed",
            result_artifact_id=review_artifact.id,
            created_by=user.id,
        )
        session.add(review_run)
        await session.flush()
        review_artifact.produced_by_run_id = review_run.id
        await record_human_decision(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=video_artifact.id,
            review_node_run_id=review_run.id,
            review_kind="video_drift",
            decision="approved",
            reason="人工确认成片素材可用。",
            actor_id=user.id,
            shot_version=shot.version,
            request_key=f"review-fixture-{uuid4().hex}",
        )
        formal_videos.append(video_artifact)
        shots.append(shot)
        timeline_clips.append(
            {
                "id": f"clip-{index + 1}",
                "shot_id": str(shot.id),
                "artifact_id": str(video_artifact.id),
                "order": index + 1,
                "duration_seconds": 5,
                "source_in_seconds": 0,
                "subtitle": "",
                "audio_id": None,
                "transition": None,
            }
        )
    edit = EditSession(
        project_id=project.id,
        name="Final timeline",
        status="draft",
        version=1,
        timeline={"clips": timeline_clips, "metadata": {}},
        production_lineage={"lineage_readonly": True},
        created_by=user.id,
    )
    session.add(edit)
    await session.commit()
    return project, user, edit, shots, formal_videos


async def _fake_enqueue(self: NodeRunScheduler, node_run_id: object) -> str:
    _ = self
    return f"job-{node_run_id}"
