"""P0-AGENT-1: Agent Brief/Plan generation with Fake text adapter (APP_ENV=test)."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from app.access.models import Organization, OrganizationMember, User
from app.assets.models import Shot
from app.config import Settings
from app.creation import models as _cm  # noqa: F401
from app.creation.models import AgentRun
from app.creation.service import CreationService, _parse_brief_json, _parse_plan_json
from app.execution import models as _xm  # noqa: F401
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.shot_p0 import SHOT_NODES
from app.execution.shot_review import start_shot_nodes
from app.production.models import GraphVersion
from app.providers.fake import FakeOpenAIAdapter
from app.providers.openai import AnthropicCompatibleTextAdapter
from app.runtime.scheduler import WorkerRuntime
from app.shared.base import Base
from app.shared.enums import MemberRole
from app.shared.errors import ValidationAppError
from app.shared.security import CSRF_HEADER, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "api_style",
        "base_url",
        "expected_path",
        "response_payload",
        "expected_text",
    ),
    [
        (
            "anthropic",
            "https://text.example/api",
            "/api/v1/messages",
            {"content": [{"type": "text", "text": '{"title":"Anthropic"}'}]},
            '{"title":"Anthropic"}',
        ),
        (
            "openai",
            "https://text.example/v1",
            "/v1/chat/completions",
            {"choices": [{"message": {"content": '{"title":"OpenAI"}'}}]},
            '{"title":"OpenAI"}',
        ),
    ],
)
async def test_text_adapter_uses_configured_provider_contract(
    api_style: str,
    base_url: str,
    expected_path: str,
    response_payload: dict[str, object],
    expected_text: str,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_payload)

    adapter = AnthropicCompatibleTextAdapter(
        Settings(
            app_env="development",
            text_llm_enabled=True,
            text_llm_api_key="test-provider-key",
            text_llm_base_url=base_url,
            text_llm_model="test-model",
            text_llm_api_style=api_style,
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await adapter.create(
        {"kind": "brief", "prompt": "Turn this idea into a structured brief.", "max_tokens": 321}
    )

    assert result["status"] == "succeeded"
    assert result["text"] == expected_text
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == expected_path
    assert json.loads(request.content) == {
        "model": "test-model",
        "max_tokens": 321,
        "messages": [
            {"role": "user", "content": "Turn this idea into a structured brief."}
        ],
    }
    if api_style == "anthropic":
        assert request.headers["x-api-key"] == "test-provider-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
    else:
        assert request.headers["authorization"] == "Bearer test-provider-key"
        assert "x-api-key" not in request.headers
        assert "anthropic-version" not in request.headers


@pytest.mark.asyncio
async def test_fake_agent_results_are_input_derived_without_story_specific_fixture() -> None:
    adapter = FakeOpenAIAdapter()
    clockmaker = await adapter.create(
        {
            "kind": "brief",
            "idea": "A clockmaker must repair a public tower before a festival begins.",
        }
    )
    gardener = await adapter.create(
        {
            "kind": "brief",
            "idea": "A gardener discovers a hidden map beneath an old orchard.",
        }
    )
    clockmaker_brief = json.loads(str(clockmaker["text"]))
    gardener_brief = json.loads(str(gardener["text"]))

    assert clockmaker_brief["logline"] != gardener_brief["logline"]
    assert "clockmaker" in clockmaker_brief["logline"].lower()
    assert "orchard" in gardener_brief["logline"].lower()

    plan_result = await adapter.create({"kind": "plan", "brief": clockmaker_brief})
    plan = json.loads(str(plan_result["text"]))
    rendered = json.dumps(plan).lower()
    assert len(plan["shots"]) == 10
    assert "clockmaker" in rendered
    assert "lin xia" not in rendered
    assert "neon rain witness" not in rendered
    assert len({shot["keyframe_prompt"] for shot in plan["shots"]}) == 10
    assert all(isinstance(shot["lead_identity_required"], bool) for shot in plan["shots"])


@pytest.mark.asyncio
async def test_generate_brief_and_plan_agent_retries_invalid_structured_output(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MalformedBriefAndPlanThenFakeAdapter(FakeOpenAIAdapter):
        def __init__(self) -> None:
            super().__init__()
            self._brief_attempts = 0
            self._plan_attempts = 0
            self.plan_prompts: list[str] = []

        async def create(self, request: dict[str, object]) -> dict[str, object]:
            if request.get("kind") == "brief":
                self._brief_attempts += 1
                if self._brief_attempts == 1:
                    return {
                        "remote_task_id": "malformed-brief",
                        "status": "succeeded",
                        "text": '{"logline":"incomplete"}',
                    }
            if request.get("kind") == "plan":
                self._plan_attempts += 1
                self.plan_prompts.append(str(request.get("prompt") or ""))
                if self._plan_attempts == 1:
                    return {
                        "remote_task_id": "malformed-plan",
                        "status": "succeeded",
                        "text": '{"title":"missing shots"}',
                    }
            return await super().create(request)

    adapter = MalformedBriefAndPlanThenFakeAdapter()
    monkeypatch.setattr(
        "app.creation.service.get_openai_adapter",
        lambda *, allow_live=False: adapter,
    )
    suffix = uuid4().hex[:8]
    user = User(
        email=f"agent-{suffix}@example.com",
        display_name="A",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"O-{suffix}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value)
    )
    await session.commit()

    svc = CreationService(session)
    started = await svc.start_project(
        organization_id=org.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="neon rain short",
    )
    rev = await svc.generate_brief_agent(
        project_id=started.project_id,
        actor=user,
        idea="霓虹雨夜女主被跟踪",
        authorize=True,
    )
    assert rev.source_kind == "agent"
    assert rev.brief.get("logline")
    assert rev.brief.get("synopsis")
    assert rev.brief.get("protagonist")
    assert rev.brief.get("conflict")
    assert rev.brief.get("episode_hook")
    assert rev.status == "draft"

    confirmed = await svc.confirm_brief(
        project_id=started.project_id, revision_id=rev.id, actor=user
    )
    assert confirmed.status == "confirmed"

    plan = await svc.generate_plan_agent(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=confirmed.id,
        authorize=True,
    )
    assert plan.plan.get("prompt")
    assert len(plan.plan.get("shots", [])) == 10
    assert all(
        shot.get("keyframe_prompt") for shot in plan.plan.get("shots", []) if isinstance(shot, dict)
    )
    assert plan.source_agent_run_id is not None

    runs = (
        (await session.execute(select(AgentRun).where(AgentRun.project_id == started.project_id)))
        .scalars()
        .all()
    )
    assert len(runs) >= 2
    assert all(r.status == "succeeded" for r in runs)

    ops = (
        (
            await session.execute(
                select(ProviderOperation).where(
                    ProviderOperation.agent_run_id.in_([r.id for r in runs])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ops) == 4
    failed_brief = [
        op
        for op in ops
        if op.operation_kind == "text.brief.generate" and op.status == "failed"
    ]
    successful_brief = [
        op for op in ops if op.operation_kind == "text.brief.generate" and op.status == "succeeded"
    ]
    assert len(failed_brief) == 1
    assert failed_brief[0].attempt_no == 1
    assert failed_brief[0].response_summary["response_chars"] > 0
    assert len(successful_brief) == 1
    assert successful_brief[0].attempt_no == 2
    failed_plan = [
        op
        for op in ops
        if op.operation_kind == "text.plan.generate" and op.status == "failed"
    ]
    successful_plan = [
        op for op in ops if op.operation_kind == "text.plan.generate" and op.status == "succeeded"
    ]
    assert len(failed_plan) == 1
    assert failed_plan[0].attempt_no == 1
    assert failed_plan[0].response_summary["response_chars"] > 0
    assert len(successful_plan) == 1
    assert successful_plan[0].attempt_no == 2
    assert len(adapter.plan_prompts) == 2
    assert "previous response failed validation" in adapter.plan_prompts[1]


def test_agent_brief_confirm_plan_api_flow(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"agent-api-{suffix}@example.com",
            "password": "password123",
            "display_name": "Agent API",
        },
    )
    assert registered.status_code == 201, registered.text

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    organization = client.post(
        "/api/v1/organizations",
        json={"name": f"AgentApiOrg-{suffix}"},
        headers={CSRF_HEADER: csrf},
    )
    assert organization.status_code == 201, organization.text

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    started = client.post(
        "/api/v1/creation/start-project",
        json={
            "organization_id": organization.json()["id"],
            "name": f"AgentApiProject-{suffix}",
            "aspect_ratio": "9:16",
            "experience_mode": "quick",
            "idea": "neon rain reunion",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert started.status_code == 201, started.text
    project_id = started.json()["project_id"]

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    brief = client.post(
        f"/api/v1/projects/{project_id}/brief/generate",
        json={"idea": "neon rain reunion", "authorize": True},
        headers={CSRF_HEADER: csrf},
    )
    assert brief.status_code == 200, brief.text
    assert brief.json()["status"] == "draft"
    revision_id = brief.json()["id"]

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    confirmed = client.post(
        f"/api/v1/projects/{project_id}/brief/{revision_id}/confirm",
        headers={CSRF_HEADER: csrf},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans/generate",
        json={
            "brief_revision_id": revision_id,
            "authorize": True,
            "idea": "",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["status"] == "draft"
    assert plan.json()["plan"]["prompt"]
    assert len(plan.json()["plan"]["shots"]) == 10

    state = client.get(f"/api/v1/projects/{project_id}/creation-state")
    assert state.status_code == 200, state.text
    assert state.json()["brief"]["id"] == revision_id
    assert state.json()["brief"]["source"] == "agent"
    assert state.json()["plan"]["id"] == plan.json()["id"]
    assert state.json()["plan"]["source"] == "agent"
    assert state.json()["plan"]["materialized"] is False
    assert len(state.json()["plan"]["plan"]["shots"]) == 10


def test_brief_parser_preserves_creative_contract() -> None:
    parsed = _parse_brief_json(
        """
        {
          "title": "雨幕证人",
          "logline": "林夏在雨夜发现跟踪者与失踪姐姐有关。",
          "synopsis": "林夏循着一枚旧徽章追查，在三个地点逐步逼近真相。",
          "protagonist": {
            "name": "林夏",
            "profile": "冷静的调查记者，外冷内热",
            "goal": "找到姐姐并确认跟踪者身份"
          },
          "conflict": "她必须在被灭口前拿到证据。",
          "stakes": "失败会失去姐姐，也会让证据永久消失。",
          "world": "近未来南方城市的霓虹雨夜",
          "tone": "悬疑、克制、紧迫",
          "audience": "18-35 岁短剧观众",
          "visual_style": "高反差霓虹，湿地反光，手持跟拍",
          "episode_hook": "跟踪者摘下帽子，竟与姐姐长着同一张脸。"
        }
        """,
        "雨夜跟踪",
    )

    assert parsed["title"] == "雨幕证人"
    assert parsed["synopsis"].startswith("林夏循着")
    assert parsed["protagonist"] == {
        "name": "林夏",
        "profile": "冷静的调查记者，外冷内热",
        "goal": "找到姐姐并确认跟踪者身份",
    }
    assert parsed["conflict"].startswith("她必须")
    assert parsed["stakes"].startswith("失败")
    assert parsed["visual_style"].startswith("高反差")
    assert parsed["episode_hook"].startswith("跟踪者")


def test_plan_parser_preserves_ten_structured_shots() -> None:
    shots = [
        {
            "shot_number": number,
            "scene_number": 1 if number <= 4 else 2,
            "location": "雨巷" if number <= 4 else "废弃车站",
            "time_of_day": "night",
            "shot_type": "wide" if number in {1, 5, 10} else "medium",
            "camera_move": "push_in",
            "visual_description": f"镜头 {number} 的明确动作与构图",
            "dialogue": "" if number % 2 else f"台词 {number}",
            "keyframe_prompt": f"9:16 cinematic shot {number}, consistent Lin Xia",
            "lead_identity_required": number not in {4, 8},
            "duration_seconds": 3.5,
        }
        for number in range(1, 11)
    ]
    parsed = _parse_plan_json(
        __import__("json").dumps(
            {
                "title": "雨幕证人 第一集",
                "episode_summary": "林夏追踪线索并在结尾识破假身份。",
                "visual_bible": {
                    "aspect_ratio": "9:16",
                    "style": "cinematic thriller",
                    "color_palette": "cyan, magenta, black",
                    "lighting": "wet neon practicals",
                    "character_continuity": "林夏始终穿黑色短风衣",
                    "negative_prompt": "deformed face, extra fingers, text",
                },
                "shots": shots,
            },
            ensure_ascii=False,
        ),
        "林夏在雨夜发现跟踪者",
    )

    assert parsed["prompt"] == shots[0]["keyframe_prompt"]
    assert parsed["episode_summary"].startswith("林夏追踪")
    assert parsed["visual_bible"]["character_continuity"] == "林夏始终穿黑色短风衣"
    assert len(parsed["shots"]) == 10
    assert parsed["shots"][9]["shot_number"] == 10
    assert parsed["shots"][9]["location"] == "废弃车站"
    invalid = __import__("json").loads(__import__("json").dumps({"shots": shots}))
    invalid["shots"][0].pop("lead_identity_required")
    with pytest.raises(ValueError, match="lead_identity_required"):
        _parse_plan_json(__import__("json").dumps(invalid), "林夏在雨夜发现跟踪者")


@pytest.mark.asyncio
async def test_confirm_plan_materializes_real_shots_and_keyframe_runs(
    session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"materialize-{suffix}@example.com",
        display_name="Materializer",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"Materialize-{suffix}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value)
    )
    await session.commit()

    service = CreationService(session)
    started = await service.start_project(
        organization_id=org.id,
        name=f"Plan-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="three shot chase",
    )
    brief = await service.update_brief_manual(
        project_id=started.project_id,
        actor=user,
        logline="林夏在雨夜追踪证人",
    )
    await service.confirm_brief(
        project_id=started.project_id,
        revision_id=brief.id,
        actor=user,
    )
    shot_plans = [
        {
            "shot_number": number,
            "scene_number": 1,
            "location": "雨巷",
            "time_of_day": "night",
            "shot_type": "medium",
            "camera_move": "tracking",
            "visual_description": f"林夏执行动作 {number}",
            "dialogue": "",
            "keyframe_prompt": f"cinematic rain shot {number}",
            "lead_identity_required": True,
            "duration_seconds": 3,
        }
        for number in range(1, 4)
    ]
    plan = await service.create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=brief.id,
        plan_body={
            "title": "雨夜追踪",
            "episode_summary": "三个连续动作镜头",
            "shots": shot_plans,
        },
    )

    result = await service.confirm_plan_and_materialize(
        project_id=started.project_id,
        plan_id=plan.id,
        actor=user,
    )

    shots = (
        (
            await session.execute(
                select(Shot).where(Shot.project_id == started.project_id).order_by(Shot.sort_order)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (await session.execute(select(NodeRun).where(NodeRun.project_id == started.project_id)))
        .scalars()
        .all()
    )

    assert len(shots) == 3
    assert len(result.node_run_ids) == 3
    assert result.node_run_id == result.node_run_ids[0]
    assert {str(run.input_snapshot["shot_id"]) for run in runs} == {str(shot.id) for shot in shots}
    assert all(run.input_snapshot["node_key"] == "keyframe" for run in runs)


@pytest.mark.asyncio
async def test_agent_plan_materialization_runs_independent_ten_shot_pipeline(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.consistency.image_embed.insightface_status",
        lambda: {"available": False, "backend": "not_provisioned"},
    )
    user = User(
        email=f"agent-pipeline-{uuid4().hex[:8]}@example.com",
        display_name="Agent Pipeline",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"AgentPipeline-{uuid4().hex[:6]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value)
    )
    await session.commit()

    service = CreationService(session)
    started = await service.start_project(
        organization_id=org.id,
        name="Agent ten-shot pipeline",
        aspect_ratio="9:16",
        actor=user,
        idea="A detective follows a neon-rain clue through one dangerous night.",
    )
    brief = await service.generate_brief_agent(
        project_id=started.project_id,
        actor=user,
        idea="A detective follows a neon-rain clue through one dangerous night.",
        authorize=True,
    )
    confirmed = await service.confirm_brief(
        project_id=started.project_id,
        revision_id=brief.id,
        actor=user,
    )
    plan = await service.generate_plan_agent(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=confirmed.id,
        authorize=True,
    )
    assert len(plan.plan["shots"]) == 10

    materialized = await service.confirm_plan_and_materialize(
        project_id=started.project_id,
        plan_id=plan.id,
        actor=user,
    )
    assert len(materialized.shot_ids) == 10
    assert len(materialized.node_run_ids) == 10

    versions = [
        await session.get(GraphVersion, graph_version_id)
        for graph_version_id in materialized.graph_version_ids
    ]
    assert all(version is not None for version in versions)
    for version in versions:
        assert version is not None
        nodes = (
            (
                await session.execute(
                    select(GraphNode).where(GraphNode.graph_version_id == version.id)
                )
            )
            .scalars()
            .all()
        )
        assert {node.node_key for node in nodes} == set(SHOT_NODES)

    worker = WorkerRuntime(session)
    await worker.process_queued(limit=20)
    for shot_id in materialized.shot_ids:
        await start_shot_nodes(
            session,
            project_id=started.project_id,
            shot_id=shot_id,
            user_id=user.id,
        )
    await session.commit()
    await worker.process_queued(limit=100)

    runs = (
        (await session.execute(select(NodeRun).where(NodeRun.project_id == started.project_id)))
        .scalars()
        .all()
    )
    done = {"completed", "cached", "completed_after_cancel"}
    artifacts_by_id = {
        artifact.id: artifact
        for artifact in (
            await session.execute(select(Artifact).where(Artifact.project_id == started.project_id))
        )
        .scalars()
        .all()
    }
    artifact_ids: set[object] = set()
    artifact_object_keys: set[str] = set()
    for shot_id in materialized.shot_ids:
        shot_runs = [
            run for run in runs if str((run.input_snapshot or {}).get("shot_id")) == str(shot_id)
        ]
        by_key = {str((run.input_snapshot or {}).get("node_key")): run for run in shot_runs}
        assert set(SHOT_NODES).issubset(by_key)
        for key in SHOT_NODES:
            run = by_key[key]
            assert run.status in done, (
                f"shot={shot_id} node={key} status={run.status} "
                f"error={run.error_code}:{run.error_summary}"
            )
            assert run.result_artifact_id is not None
            artifact = artifacts_by_id[run.result_artifact_id]
            assert artifact.produced_by_run_id == run.id
            artifact_ids.add(artifact.id)
            artifact_object_keys.add(artifact.object_key)
    assert len(artifact_ids) == 10 * len(SHOT_NODES)
    assert len(artifact_object_keys) == 10 * len(SHOT_NODES)


@pytest.mark.asyncio
async def test_shot_artifact_content_reuse_is_rejected_across_node_runs(
    session: AsyncSession,
) -> None:
    project_id = uuid4()
    user_id = uuid4()
    first = NodeRun(
        project_id=project_id,
        graph_version_id=uuid4(),
        graph_node_id=uuid4(),
        idempotency_key=f"artifact-source:{uuid4()}",
        input_hash="a" * 64,
        input_snapshot={"shot_id": str(uuid4()), "node_key": "keyframe"},
        created_by=user_id,
    )
    second = NodeRun(
        project_id=project_id,
        graph_version_id=uuid4(),
        graph_node_id=uuid4(),
        idempotency_key=f"artifact-target:{uuid4()}",
        input_hash="b" * 64,
        input_snapshot={"shot_id": str(uuid4()), "node_key": "keyframe"},
        created_by=user_id,
    )
    session.add_all([first, second])
    await session.flush()

    artifact = await get_or_create_artifact(
        session,
        project_id=project_id,
        artifact_type="image",
        object_key=f"projects/{project_id}/nodes/keyframe/{first.id}.png",
        content_hash="c" * 64,
        mime_type="image/png",
        byte_size=12,
        produced_by_run_id=first.id,
    )
    assert artifact.produced_by_run_id == first.id

    with pytest.raises(ValidationAppError, match="ARTIFACT_NOT_INDEPENDENT") as error:
        await get_or_create_artifact(
            session,
            project_id=project_id,
            artifact_type="image",
            object_key=f"projects/{project_id}/nodes/keyframe/{second.id}.png",
            content_hash="c" * 64,
            mime_type="image/png",
            byte_size=12,
            produced_by_run_id=second.id,
        )
    assert error.value.details["code"] == "ARTIFACT_NOT_INDEPENDENT"


@pytest.mark.asyncio
async def test_legacy_agent_plan_requires_regeneration_before_materialization(
    session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"legacy-plan-{suffix}@example.com",
        display_name="Legacy Plan",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"LegacyPlan-{suffix}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value)
    )
    await session.commit()

    service = CreationService(session)
    started = await service.start_project(
        organization_id=org.id,
        name=f"Legacy-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="legacy one-shot plan",
    )
    brief = await service.update_brief_manual(
        project_id=started.project_id,
        actor=user,
        logline="A complete manual brief for the legacy plan guard.",
    )
    await service.confirm_brief(
        project_id=started.project_id,
        revision_id=brief.id,
        actor=user,
    )
    plan = await service.create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=brief.id,
        plan_body={"prompt": "legacy opening keyframe"},
    )
    plan.source_agent_run_id = uuid4()
    await session.commit()

    with pytest.raises(ValidationAppError, match="exactly 10 shots") as error:
        await service.confirm_plan_and_materialize(
            project_id=started.project_id,
            plan_id=plan.id,
            actor=user,
        )

    assert error.value.details["code"] == "AGENT_PLAN_REGENERATION_REQUIRED"
    shots = (
        (await session.execute(select(Shot).where(Shot.project_id == started.project_id)))
        .scalars()
        .all()
    )
    runs = (
        (await session.execute(select(NodeRun).where(NodeRun.project_id == started.project_id)))
        .scalars()
        .all()
    )
    assert shots == []
    assert runs == []


@pytest.mark.asyncio
async def test_manual_plan_save_cannot_overwrite_agent_plan(
    session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"agent-plan-guard-{suffix}@example.com",
        display_name="Agent Plan Guard",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    org = Organization(name=f"AgentPlanGuard-{suffix}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER.value)
    )
    await session.commit()

    service = CreationService(session)
    started = await service.start_project(
        organization_id=org.id,
        name=f"AgentPlanGuard-{suffix}",
        aspect_ratio="9:16",
        actor=user,
        idea="ten shot plan",
    )
    brief = await service.update_brief_manual(
        project_id=started.project_id,
        actor=user,
        logline="A complete story.",
    )
    await service.confirm_brief(
        project_id=started.project_id,
        revision_id=brief.id,
        actor=user,
    )
    shots = [
        {
            "shot_number": number,
            "scene_number": 1,
            "visual_description": f"Story beat {number}",
            "keyframe_prompt": f"9:16 shot {number}",
            "lead_identity_required": True,
        }
        for number in range(1, 11)
    ]
    agent_plan = await service.create_or_update_plan_manual(
        project_id=started.project_id,
        actor=user,
        brief_revision_id=brief.id,
        plan_body={"prompt": "9:16 shot 1", "shots": shots},
    )
    agent_plan.source_agent_run_id = uuid4()
    await session.commit()

    with pytest.raises(ValidationAppError, match="Agent Plan is already saved") as error:
        await service.create_or_update_plan_manual(
            project_id=started.project_id,
            actor=user,
            brief_revision_id=brief.id,
            plan_body={"prompt": "manual prompt only"},
        )

    assert error.value.details["code"] == "AGENT_PLAN_MANUAL_OVERWRITE_FORBIDDEN"
    await session.refresh(agent_plan)
    assert len(agent_plan.plan["shots"]) == 10
    state = await service.get_creation_state(
        project_id=started.project_id,
        actor=user,
    )
    assert state.plan is not None
    assert state.plan.id == agent_plan.id
    assert len(state.plan.plan["shots"]) == 10
