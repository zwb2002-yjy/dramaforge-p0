"""Director formal delivery must use only accepted, ordered batch lineage."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
    ProductionBatchShot,
)
from app.director.production_service import DirectorProductionService
from app.director.shooting import SelectionPlanPayload, StoryboardPlanPayload
from app.director.snapshot_service import DirectorSnapshotService
from app.execution.models import Artifact, NodeRun
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


def _storyboard() -> dict[str, object]:
    return {
        "template_key": "live_action_dialogue_short_v1",
        "aspect_ratio": "9:16",
        "target_duration_seconds": 18,
        "shots": [
            {
                "shot_id": f"shot-{number}",
                "shot_number": number,
                "duration_seconds": "6",
                "location": "fictional room",
                "time_of_day": "night",
                "shot_type": "medium",
                "camera_move": "static",
                "characters": ["Lin"],
                "action": f"Lin performs beat {number}",
                "dialogue": [
                    {
                        "speaker": "Lin",
                        "text": f"line {number}",
                        "emotion": "restrained",
                    }
                ],
                "image_prompt": f"image {number}",
                "video_prompt": f"video {number}",
                "transition": "cut",
            }
            for number in range(1, 4)
        ],
    }


def _shooting_payloads(binding_id: str) -> dict[ArtifactKind, dict[str, object]]:
    known_line = {
        "purpose": "media",
        "quantity": 1,
        "unit_amount": "1",
        "estimated_amount": "1",
        "currency": "CNY",
        "status": "known",
    }
    plans = [
        {
            "purpose": purpose,
            "model_binding_id": binding_id,
            "provider_type": "fake",
            "protocol_profile": "fake-v1",
            "model_id": f"fake-{purpose}",
            "invoke_model_value": f"fake-{purpose}",
            "manifest_hash": hashlib.sha256(purpose.encode()).hexdigest(),
            "required_capabilities": [],
            "supported_capabilities": [],
            "evidence": {},
            "pricing_snapshot": {"unit_amount": "1", "currency": "CNY"},
            "status": "ready",
            "blockers": [],
        }
        for purpose in ("character_reference", "keyframe", "video", "voice")
    ]
    return {
        ArtifactKind.CHARACTER_BIBLE: {
            "policy": "fictional_characters_only",
            "real_person_reference_allowed": False,
            "characters": [
                {
                    "character_id": "lin",
                    "name": "Lin",
                    "age_range": "25-30",
                    "facial_features": "oval face, dark eyes",
                    "hair": "short black hair",
                    "body_shape": "slender",
                    "wardrobe": "black coat",
                    "distinguishing_features": ["small mole below left eye"],
                    "locked_prompt": "fictional Chinese woman, oval face, dark eyes",
                    "negative_prompt": "real person",
                }
            ],
        },
        ArtifactKind.VISUAL_BIBLE: {
            "medium": "photorealistic_live_action",
            "aspect_ratio": "9:16",
            "era_and_setting": "contemporary fictional apartment",
            "color_palette": "muted blue and warm amber",
            "lighting": "soft practical light",
            "lens_language": "restrained medium shots",
            "continuity_rules": ["preserve coat and hair"],
            "preview_is_generated_media": False,
        },
        ArtifactKind.VOICE_BIBLE: {
            "language": "zh-CN",
            "voice_clone_allowed": False,
            "voices": [
                {
                    "character_id": "lin",
                    "character_name": "Lin",
                    "voice_description": "calm fictional female voice",
                    "pace": "medium",
                    "emotional_range": ["restrained"],
                    "voice_clone": False,
                }
            ],
        },
        ArtifactKind.STORYBOARD_PLAN: _storyboard(),
        ArtifactKind.RISK_REPORT: {
            "status": "ready",
            "representative_shot_id": "shot-1",
            "representative_shot_reason": "dialogue and identity evidence",
            "risks": [],
        },
        ArtifactKind.SELECTION_PLAN: {
            "status": "ready",
            "plans": plans,
            "fallback_allowed": False,
            "advanced_parameters_hidden_in_quick_mode": True,
        },
        ArtifactKind.COST_ESTIMATE: {
            "pricing_snapshot_id": "verified-price-v1",
            "currency": "CNY",
            "trial": [
                {**known_line, "purpose": purpose}
                for purpose in ("character_reference", "keyframe", "video", "voice")
            ],
            "production": [
                {
                    **known_line,
                    "purpose": purpose,
                    "quantity": 3,
                    "estimated_amount": "3",
                }
                for purpose in ("character_reference", "keyframe", "video", "voice")
            ],
            "repair": [known_line],
            "trial_total": "4",
            "production_total": "12",
            "repair_total": "1",
            "requires_user_budget_limit": True,
            "disclaimer": "Provider price snapshot is frozen for this batch.",
        },
        ArtifactKind.TRIAL_PLAN: {
            "representative_shot_id": "shot-1",
            "selection_reason": "dialogue and identity evidence",
            "planned_operations": ["keyframe", "video", "voice", "composite"],
            "quality_dimensions": ["identity", "continuity"],
            "budget_authorization_required": True,
        },
    }


@pytest.mark.asyncio
async def test_materialize_production_reuses_only_identical_accepted_trial(
    session: AsyncSession,
) -> None:
    user = User(
        email=f"formal-{uuid4().hex[:8]}@example.com",
        display_name="Creator",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Formal production")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Formal short",
        aspect_ratio="9:16",
        budget_limit=Decimal("100"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status=WorkflowStatus.PRODUCTION_RUNNING.value,
        current_stage="production",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    binding_id = uuid4()
    locked_refs: dict[str, str] = {}
    for number, (kind, payload) in enumerate(_shooting_payloads(str(binding_id)).items(), 1):
        version = CreativeArtifactVersion(
            project_id=project.id,
            workflow_run_id=workflow.id,
            artifact_kind=kind.value,
            revision_no=1,
            source_kind="user",
            payload=payload,
            content_hash=hashlib.sha256(f"{kind.value}-{number}".encode()).hexdigest(),
            status="locked",
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        locked_refs[kind.value] = str(version.id)
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="production_budget",
        idempotency_key="formal-budget",
        pricing_snapshot_id="verified-price-v1",
        limit_amount=Decimal("20"),
        consumed_amount=Decimal("0"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    trial_authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="trial_budget",
        idempotency_key="trial-budget",
        pricing_snapshot_id="verified-price-v1",
        limit_amount=Decimal("2"),
        consumed_amount=Decimal("1"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(trial_authorization)
    await session.flush()
    selection_payload = SelectionPlanPayload.model_validate(
        _shooting_payloads(str(binding_id))[ArtifactKind.SELECTION_PLAN]
    ).model_dump(mode="json")
    normalized_storyboard = StoryboardPlanPayload.model_validate(_storyboard())
    trial_semantic = DirectorProductionService._shot_semantic_hash(
        shot=normalized_storyboard.shots[0].model_dump(mode="json"),
        locked_refs=locked_refs,
        selection_snapshot=selection_payload,
    )
    trial_batch = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="trial",
        idempotency_key="accepted-trial",
        status="accepted",
        budget_authorization_id=trial_authorization.id,
        locked_version_refs=locked_refs,
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot=selection_payload,
        semantic_hash=hashlib.sha256(b"accepted-trial").hexdigest(),
        created_by=user.id,
    )
    session.add(trial_batch)
    await session.flush()
    trial_reservation = BudgetReservation(
        project_id=project.id,
        batch_id=trial_batch.id,
        authorization_id=trial_authorization.id,
        idempotency_key="trial-reservation",
        reserved_amount=Decimal("1"),
        currency="CNY",
        status="settled",
    )
    session.add(trial_reservation)
    await session.flush()
    episode = Episode(
        project_id=project.id,
        episode_number=1,
        title="Formal short",
        synopsis="Director-confirmed 15–30 second short drama",
    )
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="fictional room",
        time_of_day="night",
        synopsis="Director-confirmed storyboard projection",
    )
    session.add(scene)
    await session.flush()
    shot_asset = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        shot_type="medium",
        camera_move="static",
        visual_description="Lin performs beat 1",
        dialogue="line 1",
        duration_seconds=Decimal("6"),
        status="in_production",
        sort_order=1,
    )
    session.add(shot_asset)
    await session.flush()
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_asset.id,
        template_key="trial-composite",
        created_by=user.id,
        definition={
            "nodes": [{"key": "composite", "type": "composite"}],
            "edges": [],
        },
    )
    assert graph.current_version_id is not None
    materialized = await GraphService(session).materialize_definition(
        version_id=graph.current_version_id
    )
    await GraphService(session).publish(
        version_id=graph.current_version_id, published_by=user.id
    )
    trial_run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=materialized.nodes["composite"].id,
        production_batch_id=trial_batch.id,
        budget_reservation_id=trial_reservation.id,
        attempt_no=1,
        idempotency_key="accepted-trial-composite",
        input_hash=hashlib.sha256(b"accepted-composite").hexdigest(),
        status="completed",
        input_snapshot={"node_key": "composite", "logical_shot_id": "shot-1"},
        created_by=user.id,
    )
    session.add(trial_run)
    await session.flush()
    raw = b"\x00\x00\x00\x18ftyp" + b"trial" * 20
    artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key="trial/accepted.mp4",
        content_hash=hashlib.sha256(raw).hexdigest(),
        mime_type="video/mp4",
        byte_size=len(raw),
        produced_by_run_id=trial_run.id,
    )
    session.add(artifact)
    await session.flush()
    trial_run.result_artifact_id = artifact.id
    session.add(
        ProductionBatchShot(
            project_id=project.id,
            batch_id=trial_batch.id,
            logical_shot_id="shot-1",
            shot_id=shot_asset.id,
            graph_version_id=graph.current_version_id,
            status="accepted",
            semantic_hash=trial_semantic,
            accepted_artifact_id=artifact.id,
            accepted_node_run_id=trial_run.id,
        )
    )
    trial_review = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.TRIAL_REVIEW.value,
        revision_no=1,
        source_kind="user",
        payload={
            "batch_id": str(trial_batch.id),
            "quality_report_version_id": str(uuid4()),
            "decision": "accept",
            "accepted_quality": True,
            "user_note": "accepted",
            "evidence_refs": [f"artifact:{artifact.id}"],
        },
        content_hash=hashlib.sha256(b"trial-review").hexdigest(),
        status="draft",
        created_by=user.id,
    )
    session.add(trial_review)
    await session.flush()
    locked_refs[ArtifactKind.TRIAL_REVIEW.value] = str(trial_review.id)
    workflow.current_artifact_versions = locked_refs
    session.add(
        ApprovalRecord(
            project_id=project.id,
            workflow_run_id=workflow.id,
            approval_kind="production_budget",
            idempotency_key="approve-formal-production",
            approved_artifact_versions=locked_refs,
            budget_authorization_id=authorization.id,
            approved_by=user.id,
        )
    )
    await session.commit()

    service = DirectorProductionService(session)
    reusable = await service._accepted_trial_shot(
        project_id=project.id,
        workflow_id=workflow.id,
        batch_id=trial_batch.id,
        logical_shot_id="shot-1",
    )
    assert reusable is not None
    formal_locked_refs = {
        key: value
        for key, value in locked_refs.items()
        if key != ArtifactKind.TRIAL_REVIEW.value
    }
    assert reusable.semantic_hash == service._shot_semantic_hash(
        shot=normalized_storyboard.shots[0].model_dump(mode="json"),
        locked_refs=formal_locked_refs,
        selection_snapshot=selection_payload,
    )

    batch, runs = await service.materialize_production(
        project_id=project.id,
        actor=user,
        idempotency_key="formal-materialize",
    )

    shots = list(
        (
            await session.execute(
                ProductionBatchShot.__table__.select().where(
                    ProductionBatchShot.batch_id == batch.id
                )
            )
        ).mappings()
    )
    by_logical_id = {str(row["logical_shot_id"]): row for row in shots}
    assert by_logical_id["shot-1"]["status"] == "accepted"
    assert by_logical_id["shot-1"]["accepted_artifact_id"] == artifact.id
    assert by_logical_id["shot-1"]["semantic_hash"] == trial_semantic
    assert by_logical_id["shot-1"]["graph_version_id"] is None
    assert {str(run.input_snapshot["logical_shot_id"]) for run in runs} == {
        "shot-2",
        "shot-3",
    }
    assert all(run.production_batch_id == batch.id for run in runs)
    assert all(run.budget_reservation_id is not None for run in runs)
    media_runs = [
        run
        for run in runs
        if run.input_snapshot.get("purpose")
        in {"character_reference", "keyframe", "video", "voice"}
    ]
    assert media_runs
    assert all(run.input_snapshot.get("model_binding_id") == str(binding_id) for run in media_runs)
    keyframes = [
        run for run in media_runs if run.input_snapshot.get("purpose") == "keyframe"
    ]
    videos = [run for run in media_runs if run.input_snapshot.get("purpose") == "video"]
    assert keyframes and videos
    assert all(run.input_snapshot.get("aspect_ratio") == "9:16" for run in videos)
    assert all(run.input_snapshot.get("duration_seconds") == "6" for run in videos)
    assert all(
        run.input_snapshot.get("selection_plan", {}).get("model_binding_id") == str(binding_id)
        for run in videos
    )
    assert all(run.input_snapshot.get("canonical_source_run_id") for run in keyframes)
    assert all(
        run.input_snapshot.get("locked_version_refs") == batch.locked_version_refs
        for run in media_runs
    )

    # The authorization is tied to the exact frozen price snapshot, not just
    # to an arbitrary amount/currency pair supplied by the client.
    assert batch.selection_snapshot["accepted_trial_batch_id"] == str(trial_batch.id)


@pytest.mark.asyncio
async def test_exact_production_export_excludes_history_and_preserves_order(
    session: AsyncSession,
) -> None:
    user = User(
        email=f"delivery-{uuid4().hex[:8]}@example.com",
        display_name="Creator",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Director delivery")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Accepted production",
        aspect_ratio="9:16",
        budget_limit=Decimal("100"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status=WorkflowStatus.ASSEMBLING.value,
        current_stage="production",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    storyboard = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.STORYBOARD_PLAN.value,
        revision_no=1,
        source_kind="user",
        payload=_storyboard(),
        content_hash=hashlib.sha256(b"storyboard").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    session.add(storyboard)
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="production_budget",
        idempotency_key="production-budget",
        pricing_snapshot_id="price-v1",
        limit_amount=Decimal("30"),
        consumed_amount=Decimal("0"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    batch = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="production",
        idempotency_key="formal-production",
        status="accepted",
        budget_authorization_id=authorization.id,
        locked_version_refs={ArtifactKind.STORYBOARD_PLAN.value: str(storyboard.id)},
        selected_shot_ids=["shot-1", "shot-2", "shot-3"],
        template_keys=["live_dialogue_post_dub_shot_v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={},
        semantic_hash=hashlib.sha256(b"production").hexdigest(),
        created_by=user.id,
    )
    session.add(batch)
    await session.flush()

    store = InMemoryObjectStore()
    expected_artifacts = []
    expected_runs = []
    for number in range(1, 4):
        run = NodeRun(
            project_id=project.id,
            graph_version_id=uuid4(),
            graph_node_id=uuid4(),
            production_batch_id=batch.id,
            attempt_no=1,
            idempotency_key=f"formal-composite-{number}",
            input_hash=hashlib.sha256(f"run-{number}".encode()).hexdigest(),
            status="completed",
            input_snapshot={"node_key": "composite", "logical_shot_id": f"shot-{number}"},
            created_by=user.id,
        )
        session.add(run)
        await session.flush()
        raw = b"\x00\x00\x00\x18ftyp" + bytes([number]) * 64
        stored = await store.put_bytes(
            object_key=f"formal/shot-{number}.mp4", data=raw, mime_type="video/mp4"
        )
        artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=stored.object_key,
            content_hash=stored.content_hash,
            mime_type="video/mp4",
            byte_size=stored.byte_size,
            produced_by_run_id=run.id,
        )
        session.add(artifact)
        await session.flush()
        run.result_artifact_id = artifact.id
        session.add(
            ProductionBatchShot(
                project_id=project.id,
                batch_id=batch.id,
                logical_shot_id=f"shot-{number}",
                status="accepted",
                semantic_hash=hashlib.sha256(f"shot-{number}".encode()).hexdigest(),
                accepted_artifact_id=artifact.id,
                accepted_node_run_id=run.id,
            )
        )
        expected_artifacts.append(artifact.id)
        expected_runs.append(run.id)

    old_run = NodeRun(
        project_id=project.id,
        graph_version_id=uuid4(),
        graph_node_id=uuid4(),
        attempt_no=1,
        idempotency_key="unrelated-history",
        input_hash=hashlib.sha256(b"history-run").hexdigest(),
        status="completed",
        input_snapshot={"node_key": "composite", "logical_shot_id": "shot-1"},
        created_by=user.id,
    )
    session.add(old_run)
    await session.flush()
    history_bytes = b"\x00\x00\x00\x18ftyp-history"
    history_stored = await store.put_bytes(
        object_key="history/old.mp4", data=history_bytes, mime_type="video/mp4"
    )
    old_artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=history_stored.object_key,
        content_hash=history_stored.content_hash,
        mime_type="video/mp4",
        byte_size=history_stored.byte_size,
        produced_by_run_id=old_run.id,
    )
    session.add(old_artifact)
    await session.flush()
    old_run.result_artifact_id = old_artifact.id
    await session.commit()

    result = await DirectorProductionService(session).export_production(
        project_id=project.id,
        batch_id=batch.id,
        actor=user,
        store=store,
        try_ffmpeg=False,
    )

    assert result.export_status == "completed"
    assert result.source_artifact_ids == expected_artifacts
    assert result.source_node_run_ids == expected_runs
    assert old_artifact.id not in result.source_artifact_ids
    assert batch.status == "completed"
    assert workflow.status == WorkflowStatus.COMPLETED.value
    assert workflow.current_stage == "production"
    snapshot = await DirectorSnapshotService(session).get(project_id=project.id, actor=user)
    assert snapshot.latest_delivery is not None
    assert snapshot.latest_delivery.export_id == result.export_id
    assert snapshot.latest_delivery.status == "completed"
    assert [item.kind for item in snapshot.latest_delivery.items[:3]] == [
        "video",
        "video",
        "video",
    ]
    assert snapshot.latest_delivery.items[0].object_key == "formal/shot-1.mp4"
