"""Authenticated HTTP acceptance -> Director worker -> explicit Proposal Apply on PG.

Only the external text HTTP transport and checkpoint storage are synthetic.
Authentication, workspace selection, application-role RLS, durable acceptance,
the Outbox fact, the worker adoption (epoch/lease fencing), resolver, adapter,
Agent service, proposal creation and Apply remain the product implementations.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.config import clear_settings_cache, get_settings
from app.director import agent_worker
from app.director.agent_tools import ToolExecutor
from app.director.agent_worker import execute_accepted_agent_turn
from app.director.assistant_models import DirectorMessage, DirectorToolCall
from app.director.invocation_models import DirectorInvocation
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.events.models import OutboxEvent
from app.execution.models import NodeRun, ProviderOperation
from app.main import create_app
from app.providers.litellm_gateway.client import LiteLLMGatewayClient
from app.providers.litellm_gateway.management import GatewayManagementClient, GatewayReference
from app.providers.litellm_gateway.management_service import GatewayModelService
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.models import ProviderConnection
from app.shared.db import get_session
from app.shared.model_registry import load_all_models
from app.shared.security import CSRF_HEADER, hash_password
from cryptography.fernet import Fernet
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
    _sync_url,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_gateway_model_management import ProxyFixture, model

PASSWORD = "synthetic-agent-http-password"
SUGGESTED_PROMPT = "Keep the documented stone arches and the original bridge proportions."


@dataclass(frozen=True)
class HttpDatabase:
    name: str
    engine: Engine


@pytest.fixture(scope="module")
def http_database() -> Iterator[HttpDatabase]:
    dbname = f"dramaforge_agent_http_{uuid4().hex[:8]}"
    asyncio.run(_create_database(dbname))
    engine = create_engine(_sync_url(dbname))
    try:
        _alembic(dbname)
        load_all_models()
        yield HttpDatabase(dbname, engine)
    finally:
        engine.dispose()
        asyncio.run(_drop_database(dbname))


@dataclass
class SyntheticChat:
    shot_id: UUID
    requests: list[dict] = field(default_factory=list)
    timeout_after_submission: bool = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://proxy.internal:4000/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer restricted-data-key"
        body = json.loads(request.content)
        self.requests.append(body)
        if self.timeout_after_submission:
            raise httpx.ReadTimeout("Synthetic response lost after POST", request=request)
        names = {tool["function"]["name"] for tool in body["tools"]}
        assert {"shot_get", "shot_prompt_propose"} <= names
        assert body["parallel_tool_calls"] is False
        if len(self.requests) == 1:
            name, call_id = "shot_get", "read-shot"
            arguments = {"shot_id": str(self.shot_id)}
        elif len(self.requests) == 2:
            last = body["messages"][-1]
            assert last["role"] == "tool" and last["tool_call_id"] == "read-shot"
            receipt = json.loads(last["content"])
            assert receipt["ok"] is True and receipt["data"]["id"] == str(self.shot_id)
            name, call_id = "shot_prompt_propose", "propose-shot"
            arguments = {
                "shot_id": receipt["data"]["id"],
                "expected_version": receipt["data"]["version"],
                "image_prompt": SUGGESTED_PROMPT,
                "rationale": "Preserve the supplied cultural reference.",
            }
        else:
            raise AssertionError("The Agent must stop at the pending proposal")
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )


@dataclass
class HttpAgent:
    database: HttpDatabase
    client: httpx.AsyncClient
    app: object
    factory: async_sessionmaker[AsyncSession]
    workspace_id: UUID
    other_workspace_id: UUID
    project_id: UUID
    shot_id: UUID
    other_shot_id: UUID
    chat: SyntheticChat
    csrf: str

    @property
    def threads_path(self) -> str:
        return f"/api/v1/projects/{self.project_id}/director/threads"

    @property
    def headers(self) -> dict[str, str]:
        return {CSRF_HEADER: self.csrf}


@pytest.fixture
async def http_agent(
    http_database: HttpDatabase,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[HttpAgent]:
    contract = getattr(request, "param", "chat_tools_v1")
    for key, value in {
        "APP_ENV": "test",
        "SESSION_SECRET": "synthetic-agent-http-session-secret",
        "SESSION_COOKIE_SECURE": "false",
        "BYOK_FERNET_KEY": Fernet.generate_key().decode(),
        "BYOK_KEYRING": "",
        "BYOK_PRIMARY_KEY_VERSION": "legacy",
        "LITELLM_GATEWAY_URL": "http://proxy.internal:4000",
        "LITELLM_API_KEY": "restricted-data-key",
        "LITELLM_MODEL_ADMIN_KEY": "restricted-model-admin",
        "DIRECTOR_CHECKPOINT_DATABASE_URL": "postgresql://checkpoint.invalid/synthetic",
    }.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()
    settings = get_settings()
    admin_engine = create_async_engine(_async_url(http_database.name))
    app_engine = create_async_engine(
        _async_url(http_database.name),
        connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    try:
        async with admin_factory() as session:
            owner = User(
                email=f"http-{uuid4().hex}@example.com",
                display_name="Culture owner",
                password_hash=hash_password(PASSWORD),
            )
            session.add(owner)
            await session.flush()
            workspace = Workspace(owner_user_id=owner.id, name="Culture")
            other_workspace = Workspace(owner_user_id=owner.id, name="Different workspace")
            session.add_all([workspace, other_workspace])
            await session.flush()
            project = Project(
                workspace_id=workspace.id, name="Bridge film", aspect_ratio="16:9", budget_limit=0
            )
            session.add(project)
            await session.flush()
            episode = Episode(project_id=project.id, episode_number=1)
            session.add(episode)
            await session.flush()
            scene = Scene(
                episode_id=episode.id, scene_number=1, location_name="Old bridge", time_of_day="day"
            )
            session.add(scene)
            await session.flush()
            shots = [
                Shot(
                    project_id=project.id,
                    scene_id=scene.id,
                    shot_number=number,
                    visual_description=f"Original visual {number}",
                    image_prompt=f"Original image {number}",
                    video_prompt="Original video",
                )
                for number in (1, 2)
            ]
            session.add_all(shots)
            await session.commit()
            management = ProxyFixture()
            manager = GatewayModelService(
                session,
                settings=settings,
                client=GatewayManagementClient(
                    settings,
                    transport=httpx.MockTransport(management.handle),
                ),
            )
            connection = await manager.register(
                workspace_id=workspace.id,
                actor=owner,
                body=model().model_copy(
                    update={
                        "contract_profile": contract,
                    }
                ),
            )
            reference = GatewayReference.model_validate(connection.gateway_ref)
            session.add(
                ProductionModelProfile(
                    workspace_id=workspace.id,
                    project_id=project.id,
                    name="Configured director",
                    created_by=owner.id,
                    updated_by=owner.id,
                    bindings={
                        "planning.script": {
                            "model_id": f"litellm/{connection.id}/{reference.alias}",
                            "enabled": True,
                            "native_options": {},
                        }
                    },
                )
            )
            await session.commit()
            # Synthetic configuration only, never a generation probe.
            assert management.creates == 1

        chat = SyntheticChat(shots[0].id)
        original_client_init = LiteLLMGatewayClient.__init__

        def inject_text_transport(self, *, settings=None, transport=None, timeout_s=None):
            original_client_init(
                self,
                settings=settings,
                transport=httpx.MockTransport(chat.handle),
                timeout_s=timeout_s,
            )

        monkeypatch.setattr(LiteLLMGatewayClient, "__init__", inject_text_transport)

        @asynccontextmanager
        async def checkpoint(_settings, *, project_id):
            assert project_id == project.id
            yield MemorySaver()

        # The Worker owns the checkpoint scope; the HTTP acceptance never opens it.
        monkeypatch.setattr(agent_worker, "scoped_checkpointer", checkpoint)

        async def sessions() -> AsyncIterator[AsyncSession]:
            async with app_factory() as session:
                assert await session.scalar(text("SELECT current_user")) == "dramaforge_app"
                yield session

        app = create_app(settings)
        app.dependency_overrides[get_session] = sessions
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": owner.email,
                    "password": PASSWORD,
                },
            )
            assert login.status_code == 200, login.text
            workspaces = await client.get("/api/v1/workspaces")
            assert workspaces.status_code == 200, workspaces.text
            assert str(workspace.id) in {item["id"] for item in workspaces.json()}
            client.headers["X-Workspace-Id"] = str(workspace.id)
            csrf = await client.get("/api/v1/auth/csrf")
            assert csrf.status_code == 200, csrf.text
            yield HttpAgent(
                http_database,
                client,
                app,
                app_factory,
                workspace.id,
                other_workspace.id,
                project.id,
                shots[0].id,
                shots[1].id,
                chat,
                csrf.json()["csrf_token"],
            )
        app.dependency_overrides.clear()
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()
        clear_settings_cache()


async def _open_thread(agent: HttpAgent) -> str:
    response = await agent.client.post(
        agent.threads_path,
        json={"scope_type": "shot", "scope_entity_id": str(agent.shot_id)},
        headers=agent.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _accept(
    agent: HttpAgent,
    thread_id: str,
    body: dict[str, object],
    *,
    expected_status: int = 202,
) -> dict:
    response = await agent.client.post(
        f"{agent.threads_path}/{thread_id}/messages",
        json=body,
        headers=agent.headers,
    )
    assert response.status_code == expected_status, response.text
    return response.json()


async def _execute(agent: HttpAgent, turn_id: str) -> dict[str, object]:
    """Run the product worker adoption path for one accepted Turn."""
    return await execute_accepted_agent_turn(
        agent.factory,
        turn_id=UUID(turn_id),
        settings=get_settings(),
    )


async def _state(agent: HttpAgent, thread_id: str, request_key: str) -> dict:
    response = await agent.client.get(
        f"{agent.threads_path}/{thread_id}/requests",
        params={"request_key": request_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _settle(
    agent: HttpAgent,
    thread_id: str,
    acceptance: dict,
    *,
    attempts: int = 3,
) -> dict:
    """Execute accepted work and read the durable receipt until it is terminal."""
    for _attempt in range(attempts):
        await _execute(agent, str(acceptance["turn_id"]))
        state = await _state(agent, thread_id, str(acceptance["request_key"]))
        if state["turn"]["status"] in {"completed", "failed", "cancelled", "stale"}:
            return state
    raise AssertionError("accepted Agent work did not reach a terminal receipt")


@pytest.mark.asyncio
async def test_authenticated_agent_proposal_and_explicit_apply_are_one_current_chain(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    thread_id = await _open_thread(agent)
    path = f"{agent.threads_path}/{thread_id}/messages"
    body = {
        "content": "Read the selected shot and propose a faithful image prompt.",
        "request_key": "http-propose-once",
    }
    response = await agent.client.post(path, json=body, headers=agent.headers)
    assert response.status_code == 202, response.text
    acceptance = response.json()
    assert acceptance["status"] == "queued"
    assert acceptance["request_key"] == body["request_key"]
    assert acceptance["accepted_revision"] == 1
    assert acceptance["user_message_id"]
    assert agent.chat.requests == []
    assert acceptance["read_url"].endswith("request_key=http-propose-once")
    with Session(agent.database.engine) as session:
        queued = session.get(DirectorTurn, UUID(acceptance["turn_id"]))
        assert queued is not None and queued.status == "queued"
        assert queued.agent_lease_token is None and queued.agent_control_epoch == 0
        message = session.get(DirectorMessage, UUID(acceptance["user_message_id"]))
        assert message is not None and message.turn_id == queued.id
        outbox = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.project_id == agent.project_id,
                    OutboxEvent.topic == "director.turn.accepted",
                )
            )
        )
        assert len(outbox) == 1
        assert outbox[0].payload["turn_id"] == acceptance["turn_id"]

    state = await _settle(agent, thread_id, acceptance)
    assert state["acceptance"] == acceptance
    result = state["turn"]
    assert result["status"] == "completed" and len(result["proposal_ids"]) == 1
    assert len(agent.chat.requests) == 2
    proposal_id = result["proposal_ids"][0]
    with Session(agent.database.engine) as session:
        shot = session.get(Shot, agent.shot_id)
        assert shot is not None and shot.image_prompt == "Original image 1" and shot.version == 1
        proposal = session.get(DirectorProposal, UUID(proposal_id))
        assert proposal is not None and proposal.status == "pending"
        items = list(
            session.scalars(
                select(DirectorProposalItem).where(
                    DirectorProposalItem.proposal_id == proposal.id,
                )
            )
        )
        assert len(items) == 1 and items[0].command == "shot.update_image_prompt"
        item_id = str(items[0].id)
        invocation_models = list(
            session.scalars(
                select(DirectorInvocation.model_resolution).where(
                    DirectorInvocation.turn_id == UUID(result["turn_id"]),
                )
            )
        )
        assert len(invocation_models) == 2
        assert invocation_models[0] == invocation_models[1]
        assert invocation_models[0]["text_capabilities"]["tool_calling"] is True
        claimed = session.get(DirectorTurn, UUID(result["turn_id"]))
        assert claimed is not None
        assert claimed.agent_control_epoch == 2 and claimed.agent_lease_token is None
    replay = await agent.client.post(path, json=body, headers=agent.headers)
    assert replay.status_code == 200 and replay.json() == acceptance
    assert len(agent.chat.requests) == 2
    proposal_path = f"/api/v1/projects/{agent.project_id}/director/proposals/{proposal_id}"
    read = await agent.client.get(proposal_path)
    assert read.status_code == 200, read.text
    assert read.json()["scope_type"] == "shot"
    assert read.json()["scope_entity_id"] == str(agent.shot_id)
    assert read.json()["items"][0]["id"] == item_id
    decisions = {"decisions": [{"item_id": item_id, "decision": "accepted"}]}
    denied = await agent.client.post(f"{proposal_path}/apply", json=decisions)
    assert denied.status_code == 403
    wrong_scope = await agent.client.post(
        f"{proposal_path}/apply",
        json=decisions,
        headers={
            **agent.headers,
            "X-Workspace-Id": str(agent.other_workspace_id),
        },
    )
    assert wrong_scope.status_code in {403, 404}, wrong_scope.text
    applied = await agent.client.post(
        f"{proposal_path}/apply",
        json=decisions,
        headers=agent.headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["accepted"] == [item_id] and applied.json()["failed"] == []
    repeated = await agent.client.post(
        f"{proposal_path}/apply",
        json=decisions,
        headers=agent.headers,
    )
    assert repeated.status_code == 200 and repeated.json()["accepted"] == [item_id]
    reviewed = await agent.client.get(proposal_path)
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "applied"
    assert reviewed.json()["items"][0]["status"] == "accepted"
    after_apply_replay = await agent.client.post(path, json=body, headers=agent.headers)
    assert after_apply_replay.status_code == 200
    assert after_apply_replay.json() == acceptance
    with Session(agent.database.engine) as session:
        shot = session.get(Shot, agent.shot_id)
        other = session.get(Shot, agent.other_shot_id)
        assert shot is not None and shot.image_prompt == SUGGESTED_PROMPT and shot.version == 2
        assert shot.video_prompt == "Original video"
        assert shot.visual_description == "Original visual 1"
        assert other is not None and other.version == 1 and other.image_prompt == "Original image 2"
        assert shot.formal_keyframe_artifact_id is None and shot.formal_video_artifact_id is None
        assert (
            session.scalar(
                select(func.count(NodeRun.id)).where(
                    NodeRun.project_id == agent.project_id,
                )
            )
            == 0
        )
        # This module owns its database; a global count also detects orphan operations.
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0
        assert (
            session.scalar(
                select(func.count(DirectorToolCall.id)).where(
                    DirectorToolCall.project_id == agent.project_id,
                )
            )
            == 2
        )
    assert len(agent.chat.requests) == 2


@pytest.mark.asyncio
async def test_explicit_agent_rejection_is_idempotent_and_never_changes_shots(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    with Session(agent.database.engine) as session:
        original_shots = {
            shot.id: {column.key: getattr(shot, column.key) for column in Shot.__table__.columns}
            for shot in session.scalars(select(Shot).where(Shot.project_id == agent.project_id))
        }
    thread_id = await _open_thread(agent)
    message_path = f"{agent.threads_path}/{thread_id}/messages"
    body = {"content": "Suggest a careful image prompt.", "request_key": "reject-proposal"}
    acceptance = await _accept(agent, thread_id, body)
    state = await _settle(agent, thread_id, acceptance)
    assert state["turn"]["status"] == "completed"
    proposal_id = state["turn"]["proposal_ids"][0]
    path = f"/api/v1/projects/{agent.project_id}/director/proposals/{proposal_id}"
    review = await agent.client.get(path)
    assert review.status_code == 200 and review.json()["status"] == "pending"
    item_id = review.json()["items"][0]["id"]
    decision = {"decisions": [{"item_id": item_id, "decision": "rejected"}]}
    for _attempt in range(2):
        rejected = await agent.client.post(f"{path}/apply", json=decision, headers=agent.headers)
        assert rejected.status_code == 200, rejected.text
        assert rejected.json() == {"accepted": [], "rejected": [item_id], "failed": []}
    reviewed = await agent.client.get(path)
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "decided"
    assert reviewed.json()["items"][0]["status"] == "rejected"
    replay = await agent.client.post(message_path, json=body, headers=agent.headers)
    assert replay.status_code == 200 and replay.json() == acceptance
    with Session(agent.database.engine) as session:
        after_shots = {
            shot.id: {column.key: getattr(shot, column.key) for column in Shot.__table__.columns}
            for shot in session.scalars(select(Shot).where(Shot.project_id == agent.project_id))
        }
        assert after_shots == original_shots
        assert (
            session.scalar(
                select(func.count(DirectorProposal.id)).where(
                    DirectorProposal.project_id == agent.project_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(NodeRun.id)).where(
                    NodeRun.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0
    assert len(agent.chat.requests) == 2


@pytest.mark.asyncio
async def test_real_resolver_stops_before_second_http_after_connection_is_disabled(
    http_agent: HttpAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = http_agent
    original_execute = ToolExecutor.execute
    first_invocation: dict[str, object] = {}

    async def disable_after_actual_read(self, **kwargs):
        result = await original_execute(self, **kwargs)
        if kwargs["context"].project_id == agent.project_id and kwargs["name"] == "shot_get":
            assert result.ok and not first_invocation
            assert len(agent.chat.requests) == 1
            with Session(agent.database.engine) as session:
                invocation = session.scalar(
                    select(DirectorInvocation).where(
                        DirectorInvocation.project_id == agent.project_id,
                    )
                )
                assert invocation is not None and invocation.status == "completed"
                first_invocation.update(
                    {
                        "id": invocation.id,
                        "input_hash": invocation.input_hash,
                        "model_resolution": invocation.model_resolution,
                    }
                )
                connection = session.scalar(
                    select(ProviderConnection).where(
                        ProviderConnection.workspace_id == agent.workspace_id,
                    )
                )
                assert connection is not None and connection.enabled
                connection.enabled = False
                session.commit()
        return result

    # Execute the real read and change real configuration at its completion boundary.
    # The resolver, registry, adapter and model validation remain unmodified.
    monkeypatch.setattr(ToolExecutor, "execute", disable_after_actual_read)
    thread_id = await _open_thread(agent)
    body = {"content": "Read the shot before suggesting changes.", "request_key": "binding-changed"}
    acceptance = await _accept(agent, thread_id, body)
    state = await _settle(agent, thread_id, acceptance)
    result = state["turn"]
    assert result["status"] == "stale" and result["stop_reason"] == "context_stale"
    assert result["model_calls"] == 1 and result["tool_calls"] == 1
    assert result["proposal_ids"] == [] and result["assistant_message_id"] is None
    replay = await agent.client.post(
        f"{agent.threads_path}/{thread_id}/messages", json=body, headers=agent.headers
    )
    assert replay.status_code == 200 and replay.json() == acceptance
    assert len(agent.chat.requests) == 1
    with Session(agent.database.engine) as session:
        invocations = list(
            session.scalars(
                select(DirectorInvocation).where(
                    DirectorInvocation.project_id == agent.project_id,
                )
            )
        )
        assert len(invocations) == 1 and first_invocation
        invocation = invocations[0]
        assert invocation.id == first_invocation["id"] and invocation.status == "completed"
        assert invocation.input_hash == first_invocation["input_hash"]
        assert invocation.model_resolution == first_invocation["model_resolution"]
        shot = session.get(Shot, agent.shot_id)
        assert shot is not None and shot.version == 1 and shot.image_prompt == "Original image 1"
        assert (
            session.scalar(
                select(func.count(DirectorProposal.id)).where(
                    DirectorProposal.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(NodeRun.id)).where(
                    NodeRun.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0


@pytest.mark.asyncio
async def test_real_http_unknown_submission_replays_acceptance_without_new_admission(
    http_agent: HttpAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = http_agent
    agent.chat.timeout_after_submission = True
    thread_id = await _open_thread(agent)
    path = f"{agent.threads_path}/{thread_id}/messages"
    body = {"content": "Inspect the selected shot.", "request_key": "http-unknown-submission"}
    acceptance = await _accept(agent, thread_id, body)
    state = await _settle(agent, thread_id, acceptance)
    receipt = state["turn"]
    assert receipt["status"] == "failed" and receipt["stop_reason"] == "unknown_submission"
    assert receipt["model_calls"] == 1 and receipt["tool_calls"] == 0
    assert receipt["assistant_message_id"] is None and receipt["proposal_ids"] == []
    assert len(agent.chat.requests) == 1
    with Session(agent.database.engine) as session:
        invocation = session.scalar(
            select(DirectorInvocation).where(
                DirectorInvocation.project_id == agent.project_id,
            )
        )
        assert invocation is not None and invocation.status == "unknown_submission"
        assert invocation.submission_started_at is not None
        assert invocation.validated_output is None and invocation.output_hash is None
        frozen_identity = {
            "id": invocation.id,
            "input_hash": invocation.input_hash,
            "model_resolution": json.loads(json.dumps(invocation.model_resolution)),
        }
        turn = session.get(DirectorTurn, UUID(receipt["turn_id"]))
        assert turn is not None and turn.transport_status == "unknown_submission"
        assert turn.model_resolution == frozen_identity["model_resolution"]

    # Only new-turn checkpoint eligibility changes. Auth, workspace, binding and keys stay intact.
    monkeypatch.setenv("DIRECTOR_CHECKPOINT_DATABASE_URL", "")
    clear_settings_cache()
    assert get_settings().director_checkpoint_database_url == ""
    lookup = f"{agent.threads_path}/{thread_id}/requests"
    missing = await agent.client.get(lookup, params={"request_key": "not/accepted ? 中文"})
    assert missing.status_code == 404
    assert missing.json()["details"]["code"] == "AGENT_REQUEST_NOT_FOUND"
    observed = await agent.client.get(lookup, params={"request_key": body["request_key"]})
    assert observed.status_code == 200
    assert observed.json()["acceptance"] == acceptance
    assert observed.json()["turn"] == receipt
    assert len(agent.chat.requests) == 1
    replay = await agent.client.post(path, json=body, headers=agent.headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == acceptance
    assert len(agent.chat.requests) == 1
    with Session(agent.database.engine) as session:
        invocations = list(
            session.scalars(
                select(DirectorInvocation).where(
                    DirectorInvocation.project_id == agent.project_id,
                )
            )
        )
        assert len(invocations) == 1
        invocation = invocations[0]
        assert invocation.id == frozen_identity["id"]
        assert invocation.input_hash == frozen_identity["input_hash"]
        assert invocation.model_resolution == frozen_identity["model_resolution"]
        assert invocation.status == "unknown_submission"
        assert (
            session.scalar(
                select(func.count(DirectorMessage.id)).where(
                    DirectorMessage.project_id == agent.project_id,
                    DirectorMessage.role == "assistant",
                )
            )
            == 0
        )
        for model_type in (DirectorProposal, DirectorToolCall, NodeRun):
            assert (
                session.scalar(
                    select(func.count(model_type.id)).where(
                        model_type.project_id == agent.project_id,
                    )
                )
                == 0
            )
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0


@pytest.mark.asyncio
async def test_explicit_apply_rejects_stale_agent_prompt_without_overwriting_user_edit(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    thread_id = await _open_thread(agent)
    acceptance = await _accept(
        agent,
        thread_id,
        {
            "content": "Suggest a faithful prompt for this shot.",
            "request_key": "stale-proposal",
        },
    )
    state = await _settle(agent, thread_id, acceptance)
    assert state["turn"]["status"] == "completed"
    proposal_id = state["turn"]["proposal_ids"][0]
    path = f"/api/v1/projects/{agent.project_id}/director/proposals/{proposal_id}"
    review = await agent.client.get(path)
    assert review.status_code == 200, review.text
    item_id = review.json()["items"][0]["id"]
    with Session(agent.database.engine) as session:
        shot = session.get(Shot, agent.shot_id)
        assert shot is not None
        shot.image_prompt = "User revised this prompt after reading the suggestion."
        shot.version += 1
        session.commit()
    rejected = await agent.client.post(
        f"{path}/apply",
        json={
            "decisions": [{"item_id": item_id, "decision": "accepted"}],
        },
        headers=agent.headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["accepted"] == [] and len(rejected.json()["failed"]) == 1
    with Session(agent.database.engine) as session:
        shot = session.get(Shot, agent.shot_id)
        item = session.get(DirectorProposalItem, UUID(item_id))
        assert shot is not None and shot.version == 2
        assert shot.image_prompt == "User revised this prompt after reading the suggestion."
        assert item is not None and item.status == "stale"
        assert (
            session.scalar(
                select(func.count(NodeRun.id)).where(
                    NodeRun.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0
    assert len(agent.chat.requests) == 2


@pytest.mark.asyncio
async def test_disconnected_acceptance_survives_restart_recovery_and_is_executed_once(
    http_agent: HttpAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP disconnect, worker downtime and a stale lease never lose accepted work."""
    agent = http_agent
    thread_id = await _open_thread(agent)
    body = {"content": "Read the shot after reconnecting.", "request_key": "disconnect-once"}
    acceptance = await _accept(agent, thread_id, body)
    # The client is gone: nothing was executed and no model request was submitted.
    assert agent.chat.requests == []

    # A worker that died while holding the lease is recovered as a terminal Turn.
    with Session(agent.database.engine) as session:
        turn = session.get(DirectorTurn, UUID(acceptance["turn_id"]))
        assert turn is not None
        turn.status = "thinking"
        turn.agent_lease_token = uuid4()
        turn.agent_control_epoch = 1
        turn.agent_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        turn.transport_status = "created"
        session.commit()
    from app.workers import jobs

    monkeypatch.setattr(jobs, "get_session_factory", lambda: agent.factory)
    recovered = await jobs.recover_interrupted_director_turns({})
    assert recovered["recovered"] == 1
    with Session(agent.database.engine) as session:
        failed = session.get(DirectorTurn, UUID(acceptance["turn_id"]))
        assert failed is not None and failed.status == "failed"
        assert failed.agent_lease_token is None
    # The fenced Turn is never adopted again and the model is never called.
    assert (await _execute(agent, str(acceptance["turn_id"])))["status"] == "failed"
    assert agent.chat.requests == []

    # A fresh accepted request is still discoverable and executed exactly once.
    second = await _accept(
        agent, thread_id, {"content": "Read it now.", "request_key": "disconnect-second"}
    )
    from app.shared.db import list_pending_agent_turn_rls_scopes

    async with agent.factory() as session:
        pending = await list_pending_agent_turn_rls_scopes(session, limit=10)
    assert [turn_id for turn_id, _scope in pending] == [UUID(second["turn_id"])]
    state = await _settle(agent, thread_id, second)
    assert state["turn"]["status"] == "completed"
    assert len(agent.chat.requests) == 2
    with Session(agent.database.engine) as session:
        assert (
            session.scalar(
                select(func.count(DirectorInvocation.id)).where(
                    DirectorInvocation.turn_id == UUID(second["turn_id"]),
                )
            )
            == 2
        )


@pytest.mark.asyncio
async def test_same_request_key_returns_original_acceptance_and_conflicts_on_new_input(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    thread_id = await _open_thread(agent)
    body = {"content": "Inspect the shot.", "request_key": "acceptance-identity"}
    first = await _accept(agent, thread_id, body)
    replay = await _accept(agent, thread_id, body, expected_status=200)
    assert replay == first
    assert agent.chat.requests == []
    conflict = await agent.client.post(
        f"{agent.threads_path}/{thread_id}/messages",
        json={"content": "A different instruction.", "request_key": "acceptance-identity"},
        headers=agent.headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["details"]["code"] == "AGENT_REQUEST_KEY_REUSED"
    assert agent.chat.requests == []
    with Session(agent.database.engine) as session:
        assert (
            session.scalar(
                select(func.count(DirectorTurn.id)).where(
                    DirectorTurn.project_id == agent.project_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(DirectorMessage.id)).where(
                    DirectorMessage.project_id == agent.project_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.project_id == agent.project_id,
                    OutboxEvent.topic == "director.turn.accepted",
                )
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("http_agent", ["chat_text_v1"], indirect=True)
async def test_plain_chat_contract_is_rejected_before_any_model_submission(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    thread_id = await _open_thread(agent)
    response = await agent.client.post(
        f"{agent.threads_path}/{thread_id}/messages",
        json={
            "content": "Inspect the shot",
            "request_key": "plain-chat-rejected",
        },
        headers=agent.headers,
    )
    assert response.status_code == 422, response.text
    assert "DIRECTOR_AGENT_TOOLS_UNAVAILABLE" in response.text
    assert response.json()["details"]["request_accepted"] is False
    assert agent.chat.requests == []
    with Session(agent.database.engine) as session:
        assert (
            session.scalar(
                select(func.count(DirectorInvocation.id)).where(
                    DirectorInvocation.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(DirectorTurn.id)).where(
                    DirectorTurn.project_id == agent.project_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.project_id == agent.project_id,
                    OutboxEvent.topic == "director.turn.accepted",
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_real_auth_csrf_and_selected_workspace_block_agent_before_transport(
    http_agent: HttpAgent,
) -> None:
    agent = http_agent
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=agent.app), base_url="http://testserver"
    ) as anonymous:
        denied = await anonymous.post(agent.threads_path, json={})
        assert denied.status_code == 401
    missing_csrf = await agent.client.post(agent.threads_path, json={})
    assert missing_csrf.status_code == 403
    thread_id = await _open_thread(agent)
    agent.client.headers["X-Workspace-Id"] = str(agent.other_workspace_id)
    wrong_workspace = await agent.client.post(
        f"{agent.threads_path}/{thread_id}/messages",
        json={
            "content": "Read another workspace",
            "request_key": "wrong-workspace",
        },
        headers=agent.headers,
    )
    assert wrong_workspace.status_code in {403, 404}, wrong_workspace.text
    assert agent.chat.requests == []
