"""R2b brief-to-script generation through typed Story proposals."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.config import Settings
from app.director.proposal_models import DirectorProposal
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.director.story_generation import (
    StoryDraftCandidate,
    StoryGenerationRequest,
    StoryGenerationService,
    render_story_markdown,
)
from app.director.text_transport import DirectorTextTransport
from app.director.turn_models import DirectorTurn
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry
from app.shared.base import Base
from app.shared.errors import ConflictError, ValidationAppError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MODEL_ID = "litellm/controlled-script"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"story-generation-{uuid4().hex}@example.com",
        display_name="Story Generation Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Generated Story",
        aspect_ratio="9:16",
        target_platform="short_video",
        style_bible={"tone": "restrained thriller"},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
        version=2,
    )
    session.add(project)
    await session.flush()
    session.add(
        ProductionModelProfile(
            workspace_id=workspace.id,
            project_id=project.id,
            name="Story model",
            version=4,
            is_default=False,
            bindings={
                str(ModelSlot.PLANNING_SCRIPT): {
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
    return project, user


def _registry(handler, *, configured: bool = True) -> ModelRegistry:
    settings = Settings(
        app_env="development",
        litellm_gateway_url="https://gateway.example" if configured else "",
        litellm_api_key="gateway-key" if configured else "",
    )
    manifest = litellm_logical_manifest("controlled-script")
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


def _candidate(title: str = "雨夜离站") -> dict[str, object]:
    return {
        "episode_number": 1,
        "title": title,
        "synopsis": "林墨必须在列车开走前决定是否说出真相。",
        "scenes": [
            {
                "scene_number": 1,
                "location_name": "旧车站",
                "time_of_day": "night",
                "synopsis": "雨声压住两人的告别。",
                "shots": [
                    {
                        "shot_number": 1,
                        "shot_type": "medium",
                        "visual": "林墨站在时钟下攥紧车票",
                        "dialogue": "别等我。",
                        "camera_move": "static",
                    },
                    {
                        "shot_number": 2,
                        "shot_type": "close_up",
                        "visual": "她抬眼却没有迈步",
                        "dialogue": "",
                        "camera_move": "slow_push",
                    },
                ],
            },
            {
                "scene_number": 2,
                "location_name": "月台尽头",
                "time_of_day": "night",
                "synopsis": "列车离开，真相留在原地。",
                "shots": [
                    {
                        "shot_number": 1,
                        "shot_type": "wide",
                        "visual": "列车尾灯消失在雨幕中",
                        "dialogue": "",
                        "camera_move": "tracking_out",
                    }
                ],
            },
        ],
    }


def _request(*, key: str, brief: str = "雨夜车站的克制告别短剧") -> StoryGenerationRequest:
    return StoryGenerationRequest(
        request_key=key,
        brief=brief,
        filename="generated-story.md",
    )


async def _counts(session: AsyncSession, project_id) -> dict[str, int]:
    return {
        "documents": int(
            await session.scalar(
                select(func.count(ScriptDocument.id)).where(ScriptDocument.project_id == project_id)
            )
            or 0
        ),
        "episodes": int(
            await session.scalar(
                select(func.count(Episode.id)).where(Episode.project_id == project_id)
            )
            or 0
        ),
        "scenes": int(
            await session.scalar(
                select(func.count(Scene.id))
                .select_from(Scene)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Episode.project_id == project_id)
            )
            or 0
        ),
        "shots": int(
            await session.scalar(select(func.count(Shot.id)).where(Shot.project_id == project_id))
            or 0
        ),
    }


@pytest.mark.asyncio
async def test_brief_generates_parser_compatible_proposal_without_canonical_writes(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][-1]["content"])
        assert prompt["context"]["intent"]["brief"] == "雨夜车站的克制告别短剧"
        return httpx.Response(
            200,
            headers={
                "x-litellm-call-id": "story-call-1",
                "x-litellm-model-name": "upstream/story-v1",
                "x-litellm-response-cost": "0.006",
            },
            json={
                "choices": [{"message": {"content": json.dumps(_candidate())}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 70},
                "model": "controlled-script",
            },
        )

    before = await _counts(session, project.id)
    result = await StoryGenerationService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    ).generate_proposal(
        project=project,
        actor=user,
        request=_request(key="story-turn:first"),
    )
    after = await _counts(session, project.id)
    assert before == after == {"documents": 0, "episodes": 0, "scenes": 0, "shots": 0}
    assert len(calls) == 1
    assert result.draft.title == "雨夜离站"
    assert result.draft_text.startswith("# Episode 1 — 雨夜离站")
    assert "## Scene 2 — 月台尽头 / night" in result.draft_text
    assert {item.command for item in result.proposal.items} >= {
        "story.set_script_document",
        "story.upsert_episode",
        "story.upsert_scene",
        "story.upsert_shot",
    }
    assert result.evidence.model_id == MODEL_ID
    assert result.evidence.actual_model == "upstream/story-v1"
    turn = await session.get(DirectorTurn, result.turn.id)
    assert turn is not None
    assert turn.status == "awaiting_user"
    assert turn.proposal_id == result.proposal.proposal.id
    assert turn.transport_record_id == "story-call-1"
    assert turn.provider_cost == Decimal("0.006")


@pytest.mark.asyncio
async def test_same_request_reuses_turn_and_proposal_then_changed_brief_conflicts(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_candidate())}}]},
        )

    service = StoryGenerationService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    )
    request = _request(key="story-turn:idempotent")
    first = await service.generate_proposal(project=project, actor=user, request=request)
    second = await service.generate_proposal(project=project, actor=user, request=request)
    assert calls == 1
    assert first.turn.id == second.turn.id
    assert first.proposal.proposal.id == second.proposal.proposal.id
    assert (
        await session.scalar(
            select(func.count(DirectorProposal.id)).where(DirectorProposal.project_id == project.id)
        )
    ) == 1
    with pytest.raises(ConflictError) as raised:
        await service.generate_proposal(
            project=project,
            actor=user,
            request=_request(key="story-turn:idempotent", brief="完全不同的喜剧创意"),
        )
    assert raised.value.details["code"] == "DIRECTOR_REQUEST_KEY_REUSED"


@pytest.mark.asyncio
async def test_partial_decisions_apply_only_selected_generated_story_items(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_candidate())}}]},
        )

    generated = await StoryGenerationService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    ).generate_proposal(
        project=project,
        actor=user,
        request=_request(key="story-turn:partial"),
    )
    decisions: list[ProposalDecision] = []
    for item in generated.proposal.items:
        payload = item.payload or {}
        accept = item.command in {"story.set_script_document", "story.upsert_episode"}
        accept = accept or (
            item.command in {"story.upsert_scene", "story.upsert_shot"}
            and payload.get("scene_number") == 1
            and (item.command != "story.upsert_shot" or payload.get("shot_number") == 1)
        )
        decisions.append(
            ProposalDecision(
                item_id=item.id,
                decision="accepted" if accept else "rejected",
            )
        )
    applied = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=generated.proposal.proposal.id,
        apply_input=PartialApplyInput(decisions=decisions),
    )
    assert applied.failed == []
    assert applied.accepted
    assert applied.rejected
    assert await _counts(session, project.id) == {
        "documents": 1,
        "episodes": 1,
        "scenes": 1,
        "shots": 1,
    }


@pytest.mark.asyncio
async def test_malicious_or_invalid_story_output_fails_after_one_repair(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        malicious = {**_candidate(), "command": "story.upsert_episode", "sql": "DROP TABLE"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(malicious)}}]},
        )

    with pytest.raises(ValidationAppError) as raised:
        await StoryGenerationService(
            session,
            text_transport=DirectorTextTransport(session, registry=_registry(handler)),
        ).generate_proposal(
            project=project,
            actor=user,
            request=_request(key="story-turn:malicious"),
        )
    assert raised.value.details["code"] == "INVALID_DIRECTOR_TEXT_OUTPUT"
    assert calls == 2
    turn = await session.scalar(
        select(DirectorTurn).where(DirectorTurn.request_key == "story-turn:malicious")
    )
    assert turn is not None
    assert turn.status == "failed"
    assert turn.schema_repair_count == 1
    assert await _counts(session, project.id) == {
        "documents": 0,
        "episodes": 0,
        "scenes": 0,
        "shots": 0,
    }


@pytest.mark.asyncio
async def test_unconfigured_script_model_records_failure_and_manual_path_remains(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)

    async def must_not_call(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("unconfigured text model must not send HTTP")

    with pytest.raises(ValidationAppError) as raised:
        await StoryGenerationService(
            session,
            text_transport=DirectorTextTransport(
                session, registry=_registry(must_not_call, configured=False)
            ),
        ).generate_proposal(
            project=project,
            actor=user,
            request=_request(key="story-turn:unconfigured"),
        )
    assert raised.value.details["code"] == "DIRECTOR_TEXT_MODEL_UNAVAILABLE"
    assert raised.value.details["manual_ok"] is True
    assert await _counts(session, project.id) == {
        "documents": 0,
        "episodes": 0,
        "scenes": 0,
        "shots": 0,
    }


@pytest.mark.asyncio
async def test_parser_failure_after_model_success_is_persisted(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, user = await _seed(session)
    project_id = project.id

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_candidate())}}]},
        )

    def fail_parser(_draft: str) -> None:
        raise ValidationAppError(
            "controlled parser failure",
            details={"code": "CONTROLLED_STORY_PARSE_FAILURE"},
        )

    monkeypatch.setattr("app.director.story_generation.parse_script_markdown", fail_parser)
    with pytest.raises(ValidationAppError) as raised:
        await StoryGenerationService(
            session,
            text_transport=DirectorTextTransport(session, registry=_registry(handler)),
        ).generate_proposal(
            project=project,
            actor=user,
            request=_request(key="story-turn:parser-failure"),
        )
    assert raised.value.details["code"] == "CONTROLLED_STORY_PARSE_FAILURE"
    turn = await session.scalar(
        select(DirectorTurn).where(DirectorTurn.request_key == "story-turn:parser-failure")
    )
    assert turn is not None
    assert turn.status == "failed"
    assert turn.transport_status == "succeeded"
    assert turn.wait_reason == "proposal_invalid"
    assert (
        await session.scalar(
            select(func.count(DirectorProposal.id)).where(DirectorProposal.project_id == project_id)
        )
    ) == 0


@pytest.mark.asyncio
async def test_story_changed_in_another_transaction_marks_generation_stale(tmp_path) -> None:
    database_path = tmp_path / "story-generation-stale.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        project, user = await _seed(session)

        async def handler(_request: httpx.Request) -> httpx.Response:
            async with factory() as other_session:
                other_session.add(
                    Episode(
                        project_id=project.id,
                        episode_number=9,
                        title="Concurrent user story",
                        synopsis="",
                    )
                )
                await other_session.commit()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(_candidate())}}]},
            )

        with pytest.raises(ConflictError) as raised:
            await StoryGenerationService(
                session,
                text_transport=DirectorTextTransport(session, registry=_registry(handler)),
            ).generate_proposal(
                project=project,
                actor=user,
                request=_request(key="story-turn:late"),
            )
        assert raised.value.details["code"] == "STORY_GENERATION_RESULT_STALE"
        turn = await session.scalar(
            select(DirectorTurn).where(DirectorTurn.request_key == "story-turn:late")
        )
        assert turn is not None
        assert turn.status == "stale"
        assert (
            await session.scalar(
                select(func.count(DirectorProposal.id)).where(
                    DirectorProposal.project_id == project.id
                )
            )
        ) == 0
    await engine.dispose()


def test_renderer_prevents_model_text_from_injecting_story_headings() -> None:
    draft = StoryDraftCandidate.model_validate(
        {
            **_candidate("Title\n## Scene 99 — injected / night"),
            "scenes": [
                {
                    "scene_number": 1,
                    "location_name": "Station / fake-time",
                    "time_of_day": "night",
                    "synopsis": "safe",
                    "shots": [
                        {
                            "shot_number": 1,
                            "shot_type": "wide\n### Shot 99 — injected",
                            "visual": "frame\n# Episode 9 — injected",
                            "dialogue": "",
                            "camera_move": "static",
                        }
                    ],
                }
            ],
        }
    )
    rendered = render_story_markdown(draft)
    lines = rendered.splitlines()
    assert sum(line.startswith("# Episode") for line in lines) == 1
    assert sum(line.startswith("## Scene") for line in lines) == 1
    assert sum(line.startswith("### Shot") for line in lines) == 1
    assert "\n## Scene 99" not in rendered
    assert "\n### Shot 99" not in rendered
    assert "Station ／ fake-time / night" in rendered
