"""R2a real structured text bridge and DirectorTurn evidence."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.config import Settings
from app.director.recommendation import (
    DirectorRecommendationRequest,
    DirectorRecommendationService,
)
from app.director.suggestion import ShotDirectorSuggestionRequest, ShotDirectorSuggestionService
from app.director.text_transport import DirectorTextTransport
from app.director.turn_models import DirectorTurn
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

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]
MODEL_ID = "litellm/controlled-storyboard"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[User, Project, Scene, Shot, Shot]:
    user = User(
        email=f"director-text-{uuid4().hex}@example.com",
        display_name="Director Text Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Text Director Project",
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={"tone": "restrained"},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
        version=3,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Rain station",
        time_of_day="night",
        synopsis="A farewell under rain",
        design_state={"palette": "cold blue"},
        version=2,
    )
    session.add(scene)
    await session.flush()
    shots: list[Shot] = []
    for number, visual, move in (
        (1, "Lin waits under the station clock", "static"),
        (2, "The train leaves as Lin lowers her hand", "tracking_out"),
    ):
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=number,
            shot_type="medium" if number == 1 else "wide",
            camera_move=move,
            visual_description=visual,
            dialogue="Do not wait." if number == 1 else "",
            duration_seconds=Decimal("4"),
            status="draft",
            sort_order=number,
            director_state={"action": {"description": visual}},
            image_prompt=f"image {number}",
            video_prompt=f"video {number}",
            version=4 + number,
        )
        session.add(shot)
        shots.append(shot)
    await session.flush()
    profile = ProductionModelProfile(
        workspace_id=workspace.id,
        project_id=project.id,
        name="Text profile",
        version=7,
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
    session.add(profile)
    await session.commit()
    return user, project, scene, shots[0], shots[1]


def _registry(handler: Handler, *, configured: bool = True) -> ModelRegistry:
    settings = Settings(
        app_env="development",
        litellm_gateway_url="https://gateway.example" if configured else "",
        litellm_api_key="gateway-key" if configured else "",
    )
    manifest = litellm_logical_manifest("controlled-storyboard")
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=settings,
        transport=httpx.MockTransport(handler),
    )
    registry = ModelRegistry()
    registry.register(manifest, adapter)
    return registry


def _request(scene: Scene, shot: Shot, *, key: str, instruction: str = "更克制"):
    return ShotDirectorSuggestionRequest(
        scene_id=scene.id,
        shot_id=shot.id,
        expected_shot_version=shot.version,
        user_instruction=instruction,
        request_key=key,
    )


def _valid_candidate(request: httpx.Request) -> dict[str, object]:
    body = json.loads(request.content)
    prompt = json.loads(body["messages"][-1]["content"])
    context = prompt.get("context") or prompt.get("original_context")
    shot = context["context"]["shot"]
    visual = shot["visual_description"]
    # Version is frozen outside the display context as an input version.
    version = context["input_versions"]["shot"]
    return {
        "base_shot_version": version,
        "suggested_image_prompt": f"model image: {visual}",
        "suggested_video_prompt": f"model video: {visual}",
        "suggested_director_state": shot["director_state"],
        "change_summary": f"针对当前镜头调整：{visual}",
    }


@pytest.mark.asyncio
async def test_same_model_uses_distinct_shot_context_and_persists_exact_evidence(
    session: AsyncSession,
) -> None:
    user, project, scene, first_shot, second_shot = await _seed(session)
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        candidate = _valid_candidate(request)
        return httpx.Response(
            200,
            headers={
                "x-litellm-response-cost": "0.00420000",
                "x-litellm-call-id": f"call-{len(calls)}",
                "x-litellm-model-name": "upstream/director-v1",
            },
            json={
                "choices": [{"message": {"content": json.dumps(candidate)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                "model": "controlled-storyboard",
            },
        )

    text_transport = DirectorTextTransport(session, registry=_registry(handler))
    service = ShotDirectorSuggestionService(session, text_transport=text_transport)
    first = await service.suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, first_shot, key="shot-turn:first"),
    )
    second = await service.suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, second_shot, key="shot-turn:second"),
    )

    assert len(calls) == 2
    assert first_shot.visual_description in first.suggested_video_prompt
    assert second_shot.visual_description in second.suggested_video_prompt
    assert first.director_evidence is not None
    assert second.director_evidence is not None
    assert first.director_evidence.model_id == MODEL_ID
    assert first.director_evidence.actual_model == "upstream/director-v1"
    assert first.director_evidence.model_binding_ref.endswith(f"@7:{ModelSlot.PLANNING_STORYBOARD}")
    assert first.director_evidence.context_hash != second.director_evidence.context_hash
    assert first.director_evidence.output_hash != second.director_evidence.output_hash
    assert first.director_evidence.reported_cost == "0.00420000"
    assert first.director_evidence.cost_status == "reported"

    turns = list(
        (await session.execute(select(DirectorTurn).order_by(DirectorTurn.request_key))).scalars()
    )
    assert len(turns) == 2
    assert {turn.status for turn in turns} == {"awaiting_user"}
    assert {turn.transport_record_id for turn in turns} == {"call-1", "call-2"}
    assert all(turn.token_usage == {"prompt_tokens": 20, "completion_tokens": 10} for turn in turns)
    assert all(turn.provider_cost == Decimal("0.00420000") for turn in turns)
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
    assert await session.scalar(select(func.count()).select_from(Artifact)) == 0
    stored_shots = list((await session.execute(select(Shot).order_by(Shot.shot_number))).scalars())
    assert [shot.version for shot in stored_shots] == [5, 6]
    assert [shot.formal_video_artifact_id for shot in stored_shots] == [None, None]


@pytest.mark.asyncio
async def test_request_key_replays_stored_result_without_second_model_call(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_valid_candidate(request))}}],
                "usage": {},
                "model": "controlled-storyboard",
            },
        )

    service = ShotDirectorSuggestionService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    )
    request = _request(scene, shot, key="shot-turn:idempotent")
    first = await service.suggest(project_id=project.id, actor=user, request=request)
    second = await service.suggest(project_id=project.id, actor=user, request=request)
    assert calls == 1
    assert first.director_evidence is not None
    assert second.director_evidence is not None
    assert first.director_evidence.turn_id == second.director_evidence.turn_id
    assert second.director_evidence.cost_status == "unknown"
    assert second.director_evidence.reported_cost is None


@pytest.mark.asyncio
async def test_proactive_recommendation_uses_the_same_real_text_bridge(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][-1]["content"])
        context = prompt["context"]
        shot_context = context["context"]["shot"]
        recommendation = {
            "base_shot_version": context["input_versions"]["shot"],
            "scope": "shot",
            "category": "CAMERA_MOTION",
            "current_state": f"当前运镜：{shot_context['camera_move']}",
            "suggested_change": "保持静止，不要推进镜头",
            "reason": "用户意图需要克制的观察感。",
            "expected_effect": "避免运镜盖过表演。",
            "risk": "画面动势较弱。",
            "affected_facts": ["shot.director_state.camera"],
            "typed_operations": [
                {
                    "op": "update_director_state",
                    "field": "camera",
                    "value": {"movement": "static"},
                }
            ],
        }
        return httpx.Response(
            200,
            headers={"x-litellm-call-id": "recommendation-call"},
            json={
                "choices": [{"message": {"content": json.dumps(recommendation)}}],
                "model": "controlled-storyboard",
            },
        )

    result = await DirectorRecommendationService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    ).recommend(
        project_id=project.id,
        actor=user,
        request=DirectorRecommendationRequest(
            scene_id=scene.id,
            shot_id=shot.id,
            expected_shot_version=shot.version,
            request_key="shot-recommendation:real",
        ),
    )
    assert result.suggested_change == "保持静止，不要推进镜头"
    assert result.typed_operations[0].field == "camera"
    assert result.director_evidence is not None
    assert result.director_evidence.model_id == MODEL_ID
    turn = await session.get(DirectorTurn, result.director_evidence.turn_id)
    assert turn is not None
    assert turn.transport_record_id == "recommendation-call"
    assert turn.status == "awaiting_user"


@pytest.mark.asyncio
async def test_schema_repair_is_same_model_and_bounded_to_one_attempt(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        content = "not-json" if len(calls) == 1 else json.dumps(_valid_candidate(request))
        return httpx.Response(
            200,
            headers={"x-litellm-response-cost": "0.001"},
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"total_tokens": 3},
                "model": "controlled-storyboard",
            },
        )

    result = await ShotDirectorSuggestionService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    ).suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, shot, key="shot-turn:repair"),
    )
    assert len(calls) == 2
    assert {call["model"] for call in calls} == {"controlled-storyboard"}
    assert result.director_evidence is not None
    assert result.director_evidence.schema_repair_count == 1
    assert result.director_evidence.token_usage == {"total_tokens": 6}
    assert result.director_evidence.reported_cost == "0.002"


@pytest.mark.asyncio
async def test_second_invalid_or_forbidden_output_fails_without_rule_fallback(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        malicious = {
            "base_shot_version": shot.version,
            "suggested_image_prompt": "bad",
            "suggested_video_prompt": "bad",
            "suggested_director_state": {"action": {"providerRequest": {"url": "bad"}}},
            "change_summary": "bad",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(malicious)}}]},
        )

    with pytest.raises(ValidationAppError) as raised:
        await ShotDirectorSuggestionService(
            session,
            text_transport=DirectorTextTransport(session, registry=_registry(handler)),
        ).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot, key="shot-turn:malicious"),
        )
    assert raised.value.details["code"] == "INVALID_DIRECTOR_TEXT_OUTPUT"
    assert raised.value.details["manual_ok"] is True
    assert calls == 2
    turn = await session.scalar(
        select(DirectorTurn).where(DirectorTurn.request_key == "shot-turn:malicious")
    )
    assert turn is not None
    assert turn.status == "failed"
    assert turn.schema_repair_count == 1
    assert "Deterministic" not in str(turn.response_summary)


@pytest.mark.asyncio
async def test_unconfigured_model_fails_explicitly_and_records_failed_turn(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)

    async def must_not_call(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("unconfigured adapter must not make HTTP")

    with pytest.raises(ValidationAppError) as raised:
        await ShotDirectorSuggestionService(
            session,
            text_transport=DirectorTextTransport(
                session, registry=_registry(must_not_call, configured=False)
            ),
        ).suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot, key="shot-turn:unconfigured"),
        )
    assert raised.value.details["code"] == "DIRECTOR_TEXT_MODEL_UNAVAILABLE"
    assert raised.value.details["manual_ok"] is True
    turn = await session.scalar(
        select(DirectorTurn).where(DirectorTurn.request_key == "shot-turn:unconfigured")
    )
    assert turn is not None
    assert turn.status == "failed"
    assert turn.wait_reason == "model_failed"
    assert turn.cost_status == "unknown"
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0


@pytest.mark.asyncio
async def test_reusing_request_key_for_changed_context_fails_closed(
    session: AsyncSession,
) -> None:
    user, project, scene, shot, _other = await _seed(session)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_valid_candidate(request))}}]},
        )

    service = ShotDirectorSuggestionService(
        session,
        text_transport=DirectorTextTransport(session, registry=_registry(handler)),
    )
    key = "shot-turn:reused"
    await service.suggest(
        project_id=project.id,
        actor=user,
        request=_request(scene, shot, key=key, instruction="不要推进镜头"),
    )
    with pytest.raises(ConflictError) as raised:
        await service.suggest(
            project_id=project.id,
            actor=user,
            request=_request(scene, shot, key=key, instruction="改为快速推进"),
        )
    assert raised.value.details["code"] == "DIRECTOR_REQUEST_KEY_REUSED"


@pytest.mark.asyncio
async def test_shot_changed_in_another_transaction_marks_late_result_stale(tmp_path) -> None:
    database_path = tmp_path / "director-stale.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user, project, scene, shot, _other = await _seed(session)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            candidate = _valid_candidate(request)
            async with factory() as other_session:
                await other_session.execute(
                    update(Shot).where(Shot.id == shot.id).values(version=shot.version + 1)
                )
                await other_session.commit()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(candidate)}}]},
            )

        with pytest.raises(ConflictError) as raised:
            await ShotDirectorSuggestionService(
                session,
                text_transport=DirectorTextTransport(session, registry=_registry(handler)),
            ).suggest(
                project_id=project.id,
                actor=user,
                request=_request(scene, shot, key="shot-turn:late-result"),
            )
        assert raised.value.details["code"] == "SHOT_SUGGESTION_RESULT_STALE"
        assert calls == 1
        turn = await session.scalar(
            select(DirectorTurn).where(DirectorTurn.request_key == "shot-turn:late-result")
        )
        assert turn is not None
        assert turn.status == "stale"
        assert turn.wait_reason == "context_changed"
        assert turn.transport_status == "succeeded"
        stored = await session.get(Shot, shot.id)
        assert stored is not None
        assert stored.version == 6
    await engine.dispose()


@pytest.mark.asyncio
async def test_rejected_context_new_request_key_never_calls_text_provider(session: AsyncSession):
    from app.director.turn_service import DirectorTurnService

    user, project, scene, shot, _second = await _seed(session)
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(_valid_candidate(request))}}],
        })

    bridge = DirectorTextTransport(session, registry=_registry(handler))
    service = ShotDirectorSuggestionService(session, text_transport=bridge)
    result = await service.suggest(
        project_id=project.id, actor=user, request=_request(scene, shot, key="rejection:one"),
    )
    turn = await session.get(DirectorTurn, result.director_evidence.turn_id)
    await DirectorTurnService(session).record_user_decision(
        project_id=project.id, turn_id=turn.id, expected_revision=turn.revision,
        decision="reject", accepted_operation_indices=[],
    )
    await session.commit()
    with pytest.raises(ConflictError) as rejected:
        await service.suggest(
            project_id=project.id, actor=user,
            request=_request(scene, shot, key="rejection:new-key"),
        )
    assert rejected.value.details["code"] == "DIRECTOR_CONTEXT_REJECTED"
    assert len(calls) == 1
    assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 1
    await service.suggest(
        project_id=project.id, actor=user,
        request=_request(scene, shot, key="rejection:changed", instruction="Changed goal"),
    )
    assert len(calls) == 2
