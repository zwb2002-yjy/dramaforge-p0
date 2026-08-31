"""P9-04A typed edit-session proposal command and stale-version tests."""

from __future__ import annotations

import math
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Asset, AssetVersion, Episode, Scene, Shot
from app.director.proposal_commands import (
    COMMAND_WHITELIST,
    ProposalCommandError,
    ProposalCommandRegistry,
)
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import (
    PartialApplyInput,
    ProposalDecision,
    ProposalService,
)
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.models import GraphVersion, ProductionGraph
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(
    session: AsyncSession,
) -> tuple[Project, EditSession, User, Shot, Asset, ProductionGraph, NodeRun, ProviderOperation]:
    user = User(
        email=f"edit-proposal-{uuid4().hex}@example.com",
        display_name="Edit Proposal",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Edit Proposal Project",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="edit proposal scene",
    )
    session.add(scene)
    await session.flush()
    asset = Asset(
        project_id=project.id,
        kind="character",
        name="Lead",
        description="Lead",
        status="active",
        metadata_json={"role": "lead"},
        version=1,
    )
    session.add(asset)
    await session.flush()
    asset_version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="Lead",
        description="Lead",
        metadata_json={"role": "lead"},
        status="formal",
        created_by=user.id,
    )
    session.add(asset_version)
    await session.flush()
    asset.current_version_id = asset_version.id
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="Lead looks toward camera",
        director_state={"camera": "static"},
        image_prompt="image A",
        video_prompt="video A",
        formal_video_artifact_id=None,
    )
    session.add(shot)
    await session.flush()
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key="edit-proposal",
        created_by=user.id,
        definition={"nodes": ["video"], "edges": []},
    )
    assert graph.current_version_id is not None
    materialized = await GraphService(session).materialize_definition(
        version_id=graph.current_version_id
    )
    node = materialized.nodes["video"]
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        idempotency_key=f"edit-proposal:{uuid4().hex}",
        input_hash="a" * 64,
        status="completed",
        input_snapshot={"shot_id": str(shot.id), "stage": "video"},
        output_summary={"source": "test"},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="stored",
        object_key=f"edit-proposal/{uuid4().hex}.mp4",
        content_hash="b" * 64,
        mime_type="video/mp4",
        byte_size=1,
        duration_seconds=Decimal("2"),
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    run.result_artifact_id = artifact.id
    shot.formal_video_artifact_id = artifact.id
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider="fake",
        actual_model="fake-video",
        request_fingerprint="c" * 64,
        status="succeeded",
        request_summary={"source": "test"},
        response_summary={"source": "test"},
        token_usage={},
        submitted_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    session.add(operation)
    await session.flush()
    timeline = {
        "clips": [
            {
                "id": "clip-a",
                "shot_id": str(shot.id),
                "artifact_id": str(artifact.id),
                "order": 1,
                "duration_seconds": 2.0,
                "subtitle": "A",
                "audio_id": None,
                "transition": {"kind": "cut"},
                "custom": {"keep": True},
            },
            {
                "id": "clip-b",
                "shot_id": str(shot.id),
                "artifact_id": str(artifact.id),
                "order": 2,
                "duration_seconds": 3.0,
                "subtitle": "B",
                "audio_id": "audio-b",
                "transition": None,
                "custom": {"keep": False},
            },
        ],
        "metadata": {"auto_built": True},
    }
    edit_session = await EditingAdapter(session).create_session(
        project_id=project.id,
        user_id=user.id,
        name="Proposal Edit",
        timeline=timeline,
        production_lineage={
            "lineage_readonly": True,
            "clips": [{"shot_id": str(shot.id), "artifact_id": str(artifact.id)}],
        },
    )
    await session.commit()
    return project, edit_session, user, shot, asset, graph, run, operation


async def _snapshot_facts(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    asset_id: UUID,
    graph_id: UUID,
    run_id: UUID,
    operation_id: UUID,
) -> dict[str, object]:
    shot = await session.get(Shot, shot_id)
    asset = await session.get(Asset, asset_id)
    graph = await session.get(ProductionGraph, graph_id)
    graph_version = (
        await session.execute(select(GraphVersion).where(GraphVersion.graph_id == graph_id))
    ).scalar_one()
    run = await session.get(NodeRun, run_id)
    operation = await session.get(ProviderOperation, operation_id)
    assert shot is not None
    assert asset is not None
    assert graph is not None
    assert run is not None
    assert operation is not None
    assert shot.project_id == project_id
    return {
        "shot": (
            shot.version,
            shot.image_prompt,
            shot.video_prompt,
            dict(shot.director_state),
            shot.formal_video_artifact_id,
        ),
        "asset": (asset.version, asset.current_version_id, asset.status),
        "graph": (graph.version, graph.current_version_id, graph.status),
        "graph_version": (graph_version.definition_hash, dict(graph_version.definition)),
        "run": (run.status, run.input_hash, dict(run.input_snapshot), run.result_artifact_id),
        "operation": (
            operation.status,
            operation.actual_provider,
            operation.actual_model,
            operation.request_fingerprint,
        ),
    }


def _plan(*operations: dict[str, object]) -> dict[str, object]:
    return {"operations": list(operations)}


def _payload(edit_session: EditSession, plan: dict[str, object]) -> dict[str, object]:
    return {"edit_session_id": str(edit_session.id), "plan": plan}


def test_edit_session_command_is_whitelisted() -> None:
    assert "edit_session.apply_timeline_plan" in COMMAND_WHITELIST


@pytest.mark.asyncio
async def test_manual_save_bumps_edit_session_version_once(session: AsyncSession) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    assert edit_session.version == 1
    lineage_before = dict(edit_session.production_lineage)
    saved = await EditingAdapter(session).save_timeline(
        project_id=project.id,
        session_id=edit_session.id,
        timeline={"clips": list(edit_session.timeline["clips"]), "metadata": {"manual": True}},
    )
    assert saved.version == 2
    assert saved.timeline["metadata"] == {"manual": True}
    assert saved.production_lineage == lineage_before
    assert user.id == saved.created_by


@pytest.mark.asyncio
async def test_valid_reorder_and_duration_plan_bumps_once_and_preserves_facts(
    session: AsyncSession,
) -> None:
    project, edit_session, user, shot, asset, graph, run, operation = await _seed(session)
    await EditingAdapter(session).save_timeline(
        project_id=project.id,
        session_id=edit_session.id,
        timeline=dict(edit_session.timeline),
    )
    await session.refresh(edit_session)
    facts_before = await _snapshot_facts(
        session,
        project_id=project.id,
        shot_id=shot.id,
        asset_id=asset.id,
        graph_id=graph.id,
        run_id=run.id,
        operation_id=operation.id,
    )
    lineage_before = dict(edit_session.production_lineage)
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    await registry.apply(
        project_id=project.id,
        command="edit_session.apply_timeline_plan",
        payload=_payload(
            edit_session,
            _plan(
                {"operation": "reorder_clips", "clip_ids": ["clip-b", "clip-a"]},
                {"operation": "set_clip_duration", "clip_id": "clip-b", "duration_seconds": 1.25},
            ),
        ),
        expected_target_version=2,
    )
    await session.refresh(edit_session)
    assert edit_session.version == 3
    clips = edit_session.timeline["clips"]
    assert [clip["id"] for clip in clips] == ["clip-b", "clip-a"]
    assert [clip["order"] for clip in clips] == [1, 2]
    assert clips[0]["duration_seconds"] == 1.25
    assert clips[0]["audio_id"] == "audio-b"
    assert clips[0]["custom"] == {"keep": False}
    assert edit_session.production_lineage == lineage_before
    facts_after = await _snapshot_facts(
        session,
        project_id=project.id,
        shot_id=shot.id,
        asset_id=asset.id,
        graph_id=graph.id,
        run_id=run.id,
        operation_id=operation.id,
    )
    assert facts_after == facts_before


@pytest.mark.asyncio
async def test_stale_edit_session_proposal_marks_item_stale_without_mutation(
    session: AsyncSession,
) -> None:
    project, edit_session, user, shot, asset, graph, run, operation = await _seed(session)
    proposal = DirectorProposal(
        project_id=project.id,
        thread_id=uuid4(),
        scope_type="edit_session",
        scope_entity_id=edit_session.id,
        status="pending",
        created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    item = DirectorProposalItem(
        proposal_id=proposal.id,
        project_id=project.id,
        command="edit_session.apply_timeline_plan",
        payload=_payload(
            edit_session,
            _plan({"operation": "set_clip_duration", "clip_id": "clip-a", "duration_seconds": 1}),
        ),
        expected_target_version=1,
        status="pending",
    )
    session.add(item)
    await session.flush()
    await EditingAdapter(session).save_timeline(
        project_id=project.id,
        session_id=edit_session.id,
        timeline=dict(edit_session.timeline),
    )
    await session.refresh(edit_session)
    before = (
        edit_session.version,
        dict(edit_session.timeline),
        dict(edit_session.production_lineage),
    )
    facts_before = await _snapshot_facts(
        session,
        project_id=project.id,
        shot_id=shot.id,
        asset_id=asset.id,
        graph_id=graph.id,
        run_id=run.id,
        operation_id=operation.id,
    )
    result = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=PartialApplyInput(
            decisions=[ProposalDecision(item_id=item.id, decision="accepted")]
        ),
    )
    await session.refresh(edit_session)
    await session.refresh(item)
    assert result.failed and "stale" in result.failed[0]["error"]
    assert edit_session.version == before[0]
    assert edit_session.timeline == before[1]
    assert edit_session.production_lineage == before[2]
    assert item.status == "stale"
    assert item.decided_at is not None
    assert (
        await _snapshot_facts(
            session,
            project_id=project.id,
            shot_id=shot.id,
            asset_id=asset.id,
            graph_id=graph.id,
            run_id=run.id,
            operation_id=operation.id,
        )
        == facts_before
    )


@pytest.mark.asyncio
async def test_rejected_edit_session_proposal_does_not_apply_or_bump(
    session: AsyncSession,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    proposal = DirectorProposal(
        project_id=project.id,
        thread_id=uuid4(),
        scope_type="edit_session",
        scope_entity_id=edit_session.id,
        status="pending",
        created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    item = DirectorProposalItem(
        proposal_id=proposal.id,
        project_id=project.id,
        command="edit_session.apply_timeline_plan",
        payload=_payload(
            edit_session,
            _plan({"operation": "set_clip_duration", "clip_id": "clip-a", "duration_seconds": 0}),
        ),
        expected_target_version=1,
        status="pending",
    )
    session.add(item)
    await session.flush()
    before = (
        edit_session.version,
        dict(edit_session.timeline),
        dict(edit_session.production_lineage),
    )
    result = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=PartialApplyInput(
            decisions=[ProposalDecision(item_id=item.id, decision="rejected")]
        ),
    )
    await session.refresh(edit_session)
    await session.refresh(item)
    assert result.rejected == [item.id]
    assert edit_session.version == before[0]
    assert edit_session.timeline == before[1]
    assert edit_session.production_lineage == before[2]
    assert item.status == "rejected"


@pytest.mark.asyncio
async def test_cross_project_edit_session_is_rejected(session: AsyncSession) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    project_b = await ProjectService(session).create_project(
        workspace_id=project.workspace_id,
        name="Other Project",
        aspect_ratio="16:9",
        actor=user,
    )
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    with pytest.raises(ProposalCommandError, match="edit session not found"):
        await registry.apply(
            project_id=project_b.id,
            command="edit_session.apply_timeline_plan",
            payload=_payload(
                edit_session,
                _plan(
                    {
                        "operation": "set_clip_duration",
                        "clip_id": "clip-a",
                        "duration_seconds": 1,
                    }
                ),
            ),
            expected_target_version=1,
        )
    await session.refresh(edit_session)
    assert edit_session.version == 1


_INVALID_PLANS: list[dict[str, object]] = [
    _plan(),
    _plan({"operation": "reorder_clips"}),
    _plan({"operation": "set_clip_duration", "clip_id": "clip-a"}),
    _plan({"operation": "reorder_clips", "clip_ids": ["clip-a", "clip-a"]}),
    _plan({"operation": "reorder_clips", "clip_ids": ["clip-a"]}),
    _plan({"operation": "reorder_clips", "clip_ids": ["clip-a", "clip-b"], "extra": True}),
    _plan({"operation": "unknown_operation", "clip_id": "clip-a"}),
    _plan({"operation": "set_clip_duration", "clip_id": "missing", "duration_seconds": 1}),
    _plan({"operation": "set_clip_duration", "clip_id": "clip-a", "duration_seconds": -1}),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": math.nan,
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": math.inf,
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "path": "timeline.clips",
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "json_patch": {},
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "production_lineage": {},
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "provider": "fake",
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "runtime_id": "x",
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "execution_plan": {},
        }
    ),
    _plan(
        {
            "operation": "set_clip_duration",
            "clip_id": "clip-a",
            "duration_seconds": 1,
            "raw_replacement": {},
        }
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", _INVALID_PLANS)
async def test_malformed_edit_session_plans_fail_closed_without_mutation(
    session: AsyncSession,
    plan: dict[str, object],
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    before = (
        edit_session.version,
        dict(edit_session.timeline),
        dict(edit_session.production_lineage),
    )
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    with pytest.raises(ProposalCommandError):
        await registry.apply(
            project_id=project.id,
            command="edit_session.apply_timeline_plan",
            payload=_payload(edit_session, plan),
            expected_target_version=1,
        )
    await session.refresh(edit_session)
    assert edit_session.version == before[0]
    assert edit_session.timeline == before[1]
    assert edit_session.production_lineage == before[2]


def test_plan_rejects_forbidden_fields_and_accepts_aliases() -> None:
    from app.editing.proposal_plan import EditSessionTimelinePlan

    with pytest.raises(ValueError):
        EditSessionTimelinePlan.model_validate(
            {
                "operations": [
                    {
                        "operation": "set_clip_duration",
                        "clip_id": "clip-a",
                        "duration_seconds": 1,
                        "sqlQuery": {},
                    }
                ]
            }
        )
    plan = EditSessionTimelinePlan.model_validate(
        {"operations": [{"kind": "reorder_clips", "clip_ids": ["clip-a"]}]}
    )
    assert plan.operations[0].operation == "reorder_clips"
