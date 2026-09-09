"""R2c real text Director bridge for persisted EditSession proposals."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.config import Settings
from app.director.editing_suggestion import (
    EditingDirectorSuggestionRequest,
    EditingDirectorSuggestionService,
)
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.text_transport import DirectorTextTransport
from app.director.turn_models import DirectorTurn
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry
from app.shared.base import Base
from app.shared.errors import ConflictError, ValidationAppError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MODEL_ID = "litellm/controlled-editing"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, User, EditSession]:
    user = User(
        email=f"editing-text-{uuid4().hex}@example.com",
        display_name="Editing Text Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Editing Text Project",
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={"pacing": "restrained"},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
        version=2,
    )
    session.add(project)
    await session.flush()
    from app.access.models import ProjectCreativeProfile

    session.add(ProjectCreativeProfile(project_id=project.id, start_type="FREE",
                                       director_autonomy="ASSIST"))
    await session.flush()
    edit_session = EditSession(
        project_id=project.id,
        name="Director Cut",
        version=3,
        timeline={
            "clips": [
                {
                    "id": "clip-a",
                    "order": 1,
                    "duration_seconds": 2.0,
                    "shot_id": str(uuid4()),
                    "artifact_id": str(uuid4()),
                    "subtitle": "原字幕 A",
                },
                {
                    "id": "clip-b",
                    "order": 2,
                    "duration_seconds": 3.5,
                    "shot_id": str(uuid4()),
                    "artifact_id": str(uuid4()),
                    "subtitle": "原字幕 B",
                },
            ],
            "metadata": {
                "editor_note": "pause before the answer",
                "provider_request": "must be sanitized",
            },
        },
        production_lineage={"clips": [{"artifact_id": str(uuid4())}]},
        created_by=user.id,
    )
    session.add(edit_session)
    session.add(
        ProductionModelProfile(
            workspace_id=workspace.id,
            project_id=project.id,
            name="Editing model",
            version=6,
            is_default=False,
            bindings={
                str(ModelSlot.PLANNING_STORYBOARD): {
                    "model_id": MODEL_ID,
                    "native_options": {},
                    "enabled": True,
                }
            },
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.commit()
    return project, user, edit_session


def _registry(handler, *, configured: bool = True) -> ModelRegistry:
    settings = Settings(
        app_env="development",
        litellm_gateway_url="https://gateway.example" if configured else "",
        litellm_api_key="gateway-key" if configured else "",
    )
    manifest = litellm_logical_manifest("controlled-editing")
    registry = ModelRegistry()
    registry.register(
        manifest,
        LiteLLMModelAdapter(
            manifest,
            settings=settings,
            transport=httpx.MockTransport(handler),
        ),
    )
    return registry


def _candidate(*, target: str = "clip-a") -> dict[str, object]:
    return {
        "base_session_version": 3,
        "plan": {
            "operations": [
                {
                    "operation": "set_clip_duration",
                    "clip_id": target,
                    "duration_seconds": 2.75,
                },
                {
                    "operation": "set_clip_subtitle",
                    "clip_id": target,
                    "subtitle": "停一下。\n再回答。",
                },
            ]
        },
        "rationale": "在回答前留出停顿，并将字幕分成两个节拍。",
        "benefit": "表演呼吸和字幕节奏一致。",
        "cost": "镜头增加 0.75 秒。",
        "risk": "整体节奏略慢。",
        "impact": "仅修改当前时间线草稿中的 clip-a。",
    }


def _request(key: str) -> EditingDirectorSuggestionRequest:
    return EditingDirectorSuggestionRequest(
        expected_session_version=3,
        user_instruction="让第一段多停顿，并把字幕拆成两个节拍",
        request_key=key,
    )


@pytest.mark.asyncio
async def test_real_editing_model_receives_sanitized_timeline_and_links_one_turn_proposal(
    session: AsyncSession,
) -> None:
    project, user, edit_session = await _seed(session)
    timeline_before = deepcopy(edit_session.timeline)
    lineage_before = deepcopy(edit_session.production_lineage)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][-1]["content"])
        context = prompt["context"]["context"]["timeline"]
        assert context["session_version"] == 3
        assert [clip["clip_id"] for clip in context["clips"]] == ["clip-a", "clip-b"]
        assert [clip["duration_seconds"] for clip in context["clips"]] == [2.0, 3.5]
        assert [clip["subtitle"] for clip in context["clips"]] == ["原字幕 A", "原字幕 B"]
        assert "artifact_id" not in json.dumps(context)
        assert "provider_request" not in context["metadata"]
        return httpx.Response(
            200,
            headers={
                "x-litellm-call-id": "editing-call-1",
                "x-litellm-model-name": "upstream/editor-v1",
                "x-litellm-response-cost": "0.004",
            },
            json={
                "choices": [{"message": {"content": json.dumps(_candidate())}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20},
                "model": "controlled-editing",
            },
        )

    service = EditingDirectorSuggestionService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    )
    request = _request("editing-turn:one")
    first = await service.suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=request,
    )
    second = await service.suggest(
        project_id=project.id,
        session_id=edit_session.id,
        actor=user,
        request=request,
    )

    assert len(calls) == 1
    assert first.proposal_id == second.proposal_id
    assert first.item_id == second.item_id
    assert first.director_evidence is not None
    assert first.director_evidence.turn_id == second.director_evidence.turn_id
    assert first.director_evidence.model_id == MODEL_ID
    assert first.director_evidence.actual_model == "upstream/editor-v1"
    assert first.director_evidence.reported_cost == "0.004"
    assert first.plan.operations[1].operation == "set_clip_subtitle"
    turn = await session.get(DirectorTurn, first.director_evidence.turn_id)
    assert turn is not None
    assert turn.proposal_id == first.proposal_id
    assert turn.status == "awaiting_user"
    assert turn.transport_record_id == "editing-call-1"
    assert (
        await session.scalar(
            select(func.count(DirectorProposal.id)).where(DirectorProposal.project_id == project.id)
        )
    ) == 1
    assert (
        await session.scalar(
            select(func.count(DirectorProposalItem.id)).where(
                DirectorProposalItem.project_id == project.id
            )
        )
    ) == 1
    await session.refresh(edit_session)
    assert edit_session.version == 3
    assert edit_session.timeline == timeline_before
    assert edit_session.production_lineage == lineage_before
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
    assert await session.scalar(select(func.count()).select_from(Artifact)) == 0


@pytest.mark.asyncio
async def test_real_editing_plan_with_unknown_clip_fails_and_creates_no_proposal(
    session: AsyncSession,
) -> None:
    project, user, edit_session = await _seed(session)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_candidate(target="missing"))}}]},
        )

    with pytest.raises(ValidationAppError) as raised:
        await EditingDirectorSuggestionService(
            session,
            text_transport=DirectorTextTransport(session, registry=_registry(handler)),
        ).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=user,
            request=_request("editing-turn:missing-target"),
        )
    assert raised.value.details["code"] == "INVALID_EDITING_DIRECTOR_PLAN"
    turn = await session.scalar(
        select(DirectorTurn).where(DirectorTurn.request_key == "editing-turn:missing-target")
    )
    assert turn is not None
    assert turn.status == "failed"
    assert turn.wait_reason == "proposal_invalid"
    assert await session.scalar(select(func.count()).select_from(DirectorProposal)) == 0


@pytest.mark.asyncio
async def test_unconfigured_editing_model_is_manual_safe_without_rule_fallback(
    session: AsyncSession,
) -> None:
    project, user, edit_session = await _seed(session)

    async def must_not_call(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("unconfigured model must not send HTTP")

    with pytest.raises(ValidationAppError) as raised:
        await EditingDirectorSuggestionService(
            session,
            text_transport=DirectorTextTransport(
                session,
                registry=_registry(must_not_call, configured=False),
            ),
        ).suggest(
            project_id=project.id,
            session_id=edit_session.id,
            actor=user,
            request=_request("editing-turn:unconfigured"),
        )
    assert raised.value.details["code"] == "DIRECTOR_TEXT_MODEL_UNAVAILABLE"
    assert raised.value.details["manual_ok"] is True
    assert await session.scalar(select(func.count()).select_from(DirectorProposal)) == 0


@pytest.mark.asyncio
async def test_edit_session_changed_during_real_call_marks_turn_stale(tmp_path) -> None:
    database_path = tmp_path / "editing-text-stale.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        project, user, edit_session = await _seed(session)

        async def handler(_request: httpx.Request) -> httpx.Response:
            async with factory() as other_session:
                await other_session.execute(
                    update(EditSession).where(EditSession.id == edit_session.id).values(version=4)
                )
                await other_session.commit()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(_candidate())}}]},
            )

        with pytest.raises(ConflictError) as raised:
            await EditingDirectorSuggestionService(
                session,
                text_transport=DirectorTextTransport(session, registry=_registry(handler)),
            ).suggest(
                project_id=project.id,
                session_id=edit_session.id,
                actor=user,
                request=_request("editing-turn:stale-result"),
            )
        assert raised.value.details["code"] == "EDITING_SUGGESTION_STALE"
        turn = await session.scalar(
            select(DirectorTurn).where(DirectorTurn.request_key == "editing-turn:stale-result")
        )
        assert turn is not None
        assert turn.status == "stale"
        assert turn.transport_status == "succeeded"
        assert await session.scalar(select(func.count()).select_from(DirectorProposal)) == 0
    await engine.dispose()
