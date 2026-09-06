"""V1 G1 Story authoring proposal chain tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.director.proposal_models import DirectorProposalItem
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.director.story_proposal import create_story_proposal
from app.execution.models import NodeRun, ProviderOperation
from app.shared.base import Base
from app.shared.security import CSRF_HEADER, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"story-{uuid4().hex}@example.com",
        display_name="Story",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    return project, user


DRAFT = """# Episode 1 — 双人冲突
## Scene 1 — 咖啡厅 / day
林墨与周野在窗边对峙。
### Shot 1 — medium
Visual: 林墨抬眼看向周野
Dialogue: 你到底知道多少？
Camera: push_in
### Shot 2 — close_up
Visual: 周野手指收紧
Dialogue: 比你多。
## Scene 2 — 车库 / night
周野独自走向车门。
### Shot 1 — wide
Visual: 车库灯下一个人影
Camera: static
"""


async def _counts(session: AsyncSession, project_id: object) -> dict[str, int]:
    return {
        "documents": (
            await session.scalar(
                select(func.count(ScriptDocument.id)).where(
                    ScriptDocument.project_id == project_id
                )
            )
        )
        or 0,
        "episodes": (
            await session.scalar(
                select(func.count(Episode.id)).where(Episode.project_id == project_id)
            )
        )
        or 0,
        "scenes": (
            await session.scalar(
                select(func.count(Scene.id))
                .select_from(Scene)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Episode.project_id == project_id)
            )
        )
        or 0,
        "shots": (
            await session.scalar(
                select(func.count(Shot.id)).where(Shot.project_id == project_id)
            )
        )
        or 0,
    }


async def _proposal(session: AsyncSession, project: Project, user: User, key: str):
    return await create_story_proposal(
        session,
        project_id=project.id,
        actor=user,
        brief="双人冲突短剧",
        filename="story.md",
        draft_text=DRAFT,
        idempotency_key=key,
    )


def _accept_all(items: list[DirectorProposalItem]) -> PartialApplyInput:
    return PartialApplyInput(
        decisions=[ProposalDecision(item_id=item.id, decision="accepted") for item in items]
    )


@pytest.mark.asyncio
async def test_proposal_creation_does_not_touch_canonical_story(session: AsyncSession) -> None:
    project, user = await _seed(session)
    before = await _counts(session, project.id)
    result = await _proposal(session, project, user, f"story-{uuid4().hex}")
    after = await _counts(session, project.id)
    assert before == after
    assert len(result.items) >= 5
    assert {item.command for item in result.items} >= {
        "story.upsert_episode",
        "story.upsert_scene",
        "story.upsert_shot",
        "story.set_script_document",
    }


@pytest.mark.asyncio
async def test_whole_apply_writes_canonical_without_provider_or_execution(
    session: AsyncSession,
) -> None:
    project, user = await _seed(session)
    result = await _proposal(session, project, user, f"story-{uuid4().hex}")
    outcome = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=result.proposal.id,
        apply_input=_accept_all(result.items),
    )
    assert outcome.failed == []
    assert len(outcome.accepted) == len(result.items)
    counts = await _counts(session, project.id)
    assert counts["documents"] == 1
    assert counts["episodes"] == 1
    assert counts["scenes"] == 2
    assert counts["shots"] == 3

    assert (
        await session.scalar(
            select(func.count(NodeRun.id)).where(NodeRun.project_id == project.id)
        )
    ) == 0
    assert (
        await session.scalar(
            select(func.count(ProviderOperation.id))
            .select_from(ProviderOperation)
            .join(NodeRun, NodeRun.id == ProviderOperation.node_run_id)
            .where(
                NodeRun.project_id == project.id
            )
        )
    ) == 0


@pytest.mark.asyncio
async def test_idempotency_returns_existing_proposal(session: AsyncSession) -> None:
    project, user = await _seed(session)
    key = f"story-{uuid4().hex}"
    first = await _proposal(session, project, user, key)
    second = await _proposal(session, project, user, key)
    assert first.proposal.id == second.proposal.id
    assert len(first.items) == len(second.items)


@pytest.mark.asyncio
async def test_partial_apply_only_accepts_chosen_scene(session: AsyncSession) -> None:
    project, user = await _seed(session)
    result = await _proposal(session, project, user, f"story-{uuid4().hex}")
    chosen = [
        item
        for item in result.items
        if item.command in {
            "story.set_script_document",
            "story.upsert_episode",
        }
        or (
            item.command in {"story.upsert_scene", "story.upsert_shot"}
            and (item.payload or {}).get("scene_number") == 1
        )
    ]
    outcome = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=result.proposal.id,
        apply_input=PartialApplyInput(
            decisions=[ProposalDecision(item_id=item.id, decision="accepted") for item in chosen]
        ),
    )
    assert outcome.failed == []
    counts = await _counts(session, project.id)
    assert counts["documents"] == 1
    assert counts["episodes"] == 1
    assert counts["scenes"] == 1
    assert counts["shots"] == 2


@pytest.mark.asyncio
async def test_stale_episode_apply_fails_closed(session: AsyncSession) -> None:
    project, user = await _seed(session)
    first = await _proposal(session, project, user, f"story-{uuid4().hex}")
    await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=first.proposal.id,
        apply_input=_accept_all(first.items),
    )
    episode = await session.scalar(
        select(Episode).where(
            Episode.project_id == project.id,
            Episode.episode_number == 1,
        )
    )
    assert episode is not None
    second = await _proposal(session, project, user, f"story-{uuid4().hex}")
    episode_item = next(
        item for item in second.items if item.command == "story.upsert_episode"
    )
    episode.version += 1  # competing canonical write after proposal creation
    await session.flush()

    outcome = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=second.proposal.id,
        apply_input=PartialApplyInput(
            decisions=[ProposalDecision(item_id=episode_item.id, decision="accepted")]
        ),
    )
    assert outcome.accepted == []
    assert outcome.failed
    assert "stale" in str(outcome.failed[0].get("error")).lower()
    episode_title = await session.scalar(
        select(Episode.title).where(
            Episode.project_id == project.id,
            Episode.episode_number == 1,
        )
    )
    assert episode_title == "双人冲突"


def test_story_proposal_api_create_preview_and_apply(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"story-api-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Story API",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    csrf = str(client.get("/api/v1/auth/csrf").json()["csrf_token"])
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Story API project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])

    proposal_response = client.post(
        f"/api/v1/projects/{project_id}/story/proposals",
        json={
            "idempotency_key": f"story-api-{uuid4().hex}",
            "brief": "双人冲突",
            "filename": "api-story.md",
            "draft_text": DRAFT,
        },
        headers={CSRF_HEADER: csrf},
    )
    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()
    operations = proposal["operations"]
    assert operations
    assert proposal["status"] == "pending"

    workspace_before = client.get(f"/api/v1/projects/{project_id}/script")
    assert workspace_before.status_code == 200, workspace_before.text
    assert workspace_before.json()["episodes"] == []

    apply_response = client.post(
        f"/api/v1/projects/{project_id}/story/proposals/{proposal['id']}/apply",
        json={
            "decisions": [
                {"item_id": operation["id"], "decision": "accepted"}
                for operation in operations
            ]
        },
        headers={CSRF_HEADER: csrf},
    )
    assert apply_response.status_code == 200, apply_response.text
    result = apply_response.json()
    assert result["failed"] == []
    assert len(result["accepted"]) == len(operations)

    workspace_after = client.get(f"/api/v1/projects/{project_id}/script")
    assert workspace_after.status_code == 200, workspace_after.text
    assert workspace_after.json()["document"] is not None
    assert len(workspace_after.json()["episodes"]) == 1
    assert len(workspace_after.json()["episodes"][0]["scenes"]) == 2
