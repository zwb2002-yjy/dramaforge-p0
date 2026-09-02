"""P9-04B server-fact-driven editing Director suggestion tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Asset, Episode, Scene, Shot
from app.director.assistant_models import DirectorThread
from app.director.editing_suggestion import (
    EditingDirectorSuggestionCandidate,
    EditingDirectorSuggestionContext,
    EditingDirectorSuggestionRequest,
    EditingDirectorSuggestionService,
    EditingProactiveSuggestionRequest,
)
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.models import ProductionGraph
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import func, select, update
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
        email=f"editing-director-{uuid4().hex}@example.com",
        display_name="Editing Director",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Editing Director Project",
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
        synopsis="suggestion scene",
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
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=3,
        visual_description="Lead turns",
        director_state={"workflow_template_key": "single-pass-v1"},
        image_prompt="image A",
        video_prompt="video A",
    )
    session.add(shot)
    await session.flush()
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key="suggestion-test",
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
        idempotency_key=f"suggestion:{uuid4().hex}",
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
        object_key=f"suggestion/{uuid4().hex}.mp4",
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
    edit_session = await EditingAdapter(session).create_session(
        project_id=project.id,
        user_id=user.id,
        name="Director Cut",
        timeline={
            "clips": [
                {
                    "id": "clip-a",
                    "order": 1,
                    "duration_seconds": 2.0,
                    "shot_id": str(shot.id),
                    "artifact_id": str(artifact.id),
                    "subtitle": "A",
                },
                {
                    "id": "clip-b",
                    "order": 2,
                    "duration_seconds": 3.0,
                    "shot_id": str(shot.id),
                    "artifact_id": str(artifact.id),
                    "subtitle": "B",
                },
            ],
            "metadata": {"auto_built": True, "editor_note": "keep"},
        },
        production_lineage={
            "lineage_readonly": True,
            "clips": [{"shot_id": str(shot.id), "artifact_id": str(artifact.id)}],
        },
    )
    await session.commit()
    return project, edit_session, user, shot, asset, graph, run, operation


def _request(version: int) -> EditingDirectorSuggestionRequest:
    return EditingDirectorSuggestionRequest(
        expected_session_version=version,
        user_instruction="把节奏放慢一点",
    )


def _candidate(version: int, *, clip_ids: list[str] | None = None) -> dict[str, object]:
    ids = clip_ids or ["clip-b", "clip-a"]
    return {
        "base_session_version": version,
        "plan": {
            "operations": [
                {"operation": "reorder_clips", "clip_ids": ids},
            ]
        },
        "rationale": "让剪辑顺序服务于情绪",
        "benefit": "节奏更克制",
        "cost": "需要人工确认并保存",
        "risk": "顺序变化会改变节奏",
        "impact": "仅影响当前 EditSession",
    }


class RecordingTransport:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[EditingDirectorSuggestionContext] = []

    async def generate(self, context: EditingDirectorSuggestionContext) -> object:
        self.calls.append(context)
        return self.output


async def _proposal_counts(session: AsyncSession, project_id: UUID) -> tuple[int, int, int]:
    proposals = await session.scalar(
        select(func.count()).select_from(DirectorProposal).where(
            DirectorProposal.project_id == project_id
        )
    )
    items = await session.scalar(
        select(func.count()).select_from(DirectorProposalItem).where(
            DirectorProposalItem.project_id == project_id
        )
    )
    threads = await session.scalar(
        select(func.count()).select_from(DirectorThread).where(
            DirectorThread.project_id == project_id
        )
    )
    return int(proposals or 0), int(items or 0), int(threads or 0)


@pytest.mark.asyncio
async def test_server_truth_context_and_one_pending_proposal(session: AsyncSession) -> None:
    project, edit_session, user, shot, asset, graph, run, operation = await _seed(session)
    transport = RecordingTransport(_candidate(1))
    before = await _proposal_counts(session, project.id)
    candidate = await EditingDirectorSuggestionService(session, transport=transport).suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=_request(1),
    )
    assert isinstance(candidate, EditingDirectorSuggestionCandidate)
    assert candidate.proposal_id is not None
    assert candidate.item_id is not None
    assert candidate.candidate is not candidate
    assert candidate.candidate.model_dump(mode="json") == candidate.model_dump(
        mode="json", exclude={"proposal_id", "item_id"}
    )
    assert len(transport.calls) == 1
    context = transport.calls[0]
    assert context.project_id == project.id
    assert context.session_id == edit_session.id
    assert context.session_version == 1
    assert context.session_name == "Director Cut"
    assert [clip.clip_id for clip in context.clips] == ["clip-a", "clip-b"]
    assert [clip.order for clip in context.clips] == [1, 2]
    assert [clip.duration_seconds for clip in context.clips] == [2.0, 3.0]
    assert context.clips[0].shot_id == str(shot.id)
    assert "artifact_id" not in context.clips[0].model_dump()
    assert context.metadata == {"auto_built": True, "editor_note": "keep"}
    assert context.user_instruction == "把节奏放慢一点"
    proposals, items, threads = await _proposal_counts(session, project.id)
    assert (proposals, items, threads) == (before[0] + 1, before[1] + 1, before[2] + 1)
    proposal = (
        await session.execute(
            select(DirectorProposal).where(DirectorProposal.project_id == project.id)
        )
    ).scalar_one()
    item = (
        await session.execute(
            select(DirectorProposalItem).where(DirectorProposalItem.project_id == project.id)
        )
    ).scalar_one()
    assert candidate.proposal_id == proposal.id
    assert candidate.item_id == item.id
    assert proposal.scope_type == "edit_session"
    assert proposal.scope_entity_id == edit_session.id
    assert proposal.thread_id is not None
    assert proposal.status == "pending"
    assert item.command == "edit_session.apply_timeline_plan"
    assert item.expected_target_version == 1
    assert item.status == "pending"
    assert item.payload == {
        "edit_session_id": str(edit_session.id),
        "plan": candidate.plan.model_dump(mode="json"),
    }
    await session.refresh(edit_session)
    assert edit_session.version == 1
    assert edit_session.timeline["clips"][0]["duration_seconds"] == 2.0
    assert edit_session.production_lineage["lineage_readonly"] is True
    assert shot.version == 3
    assert asset.version == 1
    assert graph.version == 1
    assert run.status == "completed"
    assert operation.status == "succeeded"


def test_client_cannot_inject_server_timeline_or_execution_fields() -> None:
    for field in (
        "timeline",
        "production_lineage",
        "artifact_id",
        "provider",
        "runtime",
        "worker_queue",
        "execution_plan",
        "sql_query",
        "json_patch",
        "path",
        "raw_replacement",
    ):
        with pytest.raises(ValueError):
            EditingDirectorSuggestionRequest.model_validate(
                {
                    "expected_session_version": 1,
                    "user_instruction": "要求",
                    field: {},
                }
            )


@pytest.mark.asyncio
async def test_stale_before_transport_has_no_rows_or_context(session: AsyncSession) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    edit_session.version = 2
    await session.flush()
    transport = RecordingTransport(_candidate(2))
    with pytest.raises(ConflictError) as raised:
        await EditingDirectorSuggestionService(session, transport=transport).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=user,
            request=_request(1),
        )
    assert raised.value.details["code"] == "EDITING_SUGGESTION_STALE"
    assert transport.calls == []
    assert await _proposal_counts(session, project.id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_stale_during_transport_reads_persisted_version_not_identity_map(
    session: AsyncSession,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)

    class ConcurrentSavingTransport(RecordingTransport):
        async def generate(self, context: EditingDirectorSuggestionContext) -> object:
            self.calls.append(context)
            # Simulate another editor committing a version while the service's
            # ORM instance remains loaded at version 1.  The UPDATE deliberately
            # disables ORM synchronization so only a persisted-scalar query can
            # observe the concurrent change.
            await session.execute(
                update(EditSession)
                .where(
                    EditSession.project_id == project.id,
                    EditSession.id == edit_session.id,
                )
                .values(version=2)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            assert edit_session.version == context.session_version
            return _candidate(context.session_version)

    transport = ConcurrentSavingTransport(_candidate(1))
    with pytest.raises(ConflictError) as raised:
        await EditingDirectorSuggestionService(session, transport=transport).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=user,
            request=_request(1),
        )
    assert raised.value.details["code"] == "EDITING_SUGGESTION_STALE"
    assert len(transport.calls) == 1
    assert await _proposal_counts(session, project.id) == (0, 0, 0)
    assert edit_session.version == 1
    persisted_version = await session.scalar(
        select(EditSession.version).where(
            EditSession.project_id == project.id,
            EditSession.id == edit_session.id,
        )
    )
    assert persisted_version == 2


@pytest.mark.asyncio
async def test_default_deterministic_transport_uses_existing_clips_and_preserves_facts(
    session: AsyncSession,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    timeline_before = deepcopy(edit_session.timeline)
    lineage_before = deepcopy(edit_session.production_lineage)

    candidate = await EditingDirectorSuggestionService(session).suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=_request(1),
    )

    assert candidate.plan.model_dump(mode="json") == {
        "operations": [
            {"operation": "reorder_clips", "clip_ids": ["clip-b", "clip-a"]},
        ]
    }
    await session.refresh(edit_session)
    assert edit_session.timeline == timeline_before
    assert edit_session.production_lineage == lineage_before
    assert await _proposal_counts(session, project.id) == (1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        {"base_session_version": 1},
        {
            **_candidate(1),
            "forbidden": True,
        },
        {
            **_candidate(1),
            "plan": {"operations": [{"operation": "unknown", "clip_ids": ["clip-a"]}]},
        },
        {
            **_candidate(1),
            "plan": {
                "operations": [
                    {
                        "operation": "reorder_clips",
                        "clip_ids": ["clip-a", "clip-a"],
                    }
                ]
            },
        },
        {
            **_candidate(1),
            "plan": {
                "operations": [
                    {
                        "operation": "set_clip_duration",
                        "clip_id": "clip-a",
                        "duration_seconds": -1,
                    }
                ]
            },
        },
        {
            **_candidate(1),
            "plan": {
                "operations": [
                    {
                        "operation": "set_clip_duration",
                        "clip_id": "clip-a",
                        "duration_seconds": 1,
                        "production_lineage": {},
                    }
                ]
            },
        },
    ],
)
async def test_invalid_candidate_or_plan_fails_closed(
    session: AsyncSession,
    output: object,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    before = (
        edit_session.version,
        dict(edit_session.timeline),
        dict(edit_session.production_lineage),
    )
    with pytest.raises(ValidationAppError):
        await EditingDirectorSuggestionService(
            session,
            transport=RecordingTransport(output),
        ).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=user,
            request=_request(1),
        )
    assert await _proposal_counts(session, project.id) == (0, 0, 0)
    await session.refresh(edit_session)
    assert edit_session.version == before[0]
    assert edit_session.timeline == before[1]
    assert edit_session.production_lineage == before[2]


@pytest.mark.asyncio
async def test_cross_project_session_is_rejected(session: AsyncSession) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    project_b = await ProjectService(session).create_project(
        workspace_id=project.workspace_id,
        name="Other Project",
        aspect_ratio="16:9",
        actor=user,
    )
    with pytest.raises(NotFoundError):
        await EditingDirectorSuggestionService(
            session,
            transport=RecordingTransport(_candidate(1)),
        ).suggest(
            project_id=project_b.id,
            session_id=edit_session.id,
            actor=user,
            request=_request(1),
        )
    assert await _proposal_counts(session, project.id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_non_project_owner_is_rejected_before_transport_or_persistence(
    session: AsyncSession,
) -> None:
    project, edit_session, _user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    non_owner = User(
        email=f"editing-director-non-owner-{uuid4().hex}@example.com",
        display_name="Not Project Owner",
        password_hash=hash_password("x"),
    )
    session.add(non_owner)
    await session.flush()
    transport = RecordingTransport(_candidate(1))

    with pytest.raises(ForbiddenError):
        await EditingDirectorSuggestionService(session, transport=transport).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=non_owner,
            request=_request(1),
        )

    assert transport.calls == []
    assert await _proposal_counts(session, project.id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_same_project_reuses_project_thread_and_creates_two_proposals(
    session: AsyncSession,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    service = EditingDirectorSuggestionService(
        session,
        transport=RecordingTransport(_candidate(1)),
    )
    await service.suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=_request(1),
    )
    await service.suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=_request(1),
    )
    assert await _proposal_counts(session, project.id) == (2, 2, 1)
    threads = (
        await session.execute(
            select(DirectorThread).where(
                DirectorThread.project_id == project.id,
                DirectorThread.scope_type == "project",
                DirectorThread.scope_entity_id == project.id,
            )
        )
    ).scalars().all()
    assert len(threads) == 1
    assert threads[0].scope_type == "project"
    assert threads[0].scope_entity_id == project.id
    proposals = (
        await session.execute(
            select(DirectorProposal)
            .where(DirectorProposal.project_id == project.id)
            .order_by(DirectorProposal.created_at, DirectorProposal.id)
        )
    ).scalars().all()
    assert len(proposals) == 2
    assert {proposal.thread_id for proposal in proposals} == {threads[0].id}
    assert {proposal.scope_type for proposal in proposals} == {"edit_session"}
    assert {proposal.scope_entity_id for proposal in proposals} == {edit_session.id}


def test_proactive_request_forbids_user_instruction() -> None:
    with pytest.raises(ValueError):
        EditingProactiveSuggestionRequest.model_validate(
            {
                "expected_session_version": 1,
                "user_instruction": "客户端不能上传",
            }
        )


@pytest.mark.asyncio
async def test_proactive_suggestion_works_without_instruction(
    session: AsyncSession,
) -> None:
    project, edit_session, user, _shot, _asset, _graph, _run, _operation = await _seed(session)
    result = await EditingDirectorSuggestionService(session).suggest_proactive(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=EditingProactiveSuggestionRequest(
            expected_session_version=edit_session.version,
        ),
    )
    assert result.candidate.base_session_version == edit_session.version
    assert result.proposal_id
    assert result.item_id
    assert await _proposal_counts(session, project.id) == (1, 1, 1)
