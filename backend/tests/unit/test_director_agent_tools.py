"""Read tools enforce authorization, scope, versions and bounded safe output."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.agent_read_service import AgentReadService
from app.assets.models import Asset, Episode, Scene, Shot
from app.director.agent_proposals import ShotPromptProposalInput, create_agent_shot_proposal
from app.director.agent_tools import ToolContext, ToolExecutor, ToolRegistry
from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.shared.base import Base
from app.shared.errors import ConflictError, ForbiddenError, UnauthorizedError, ValidationAppError
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass
class World:
    executor: ToolExecutor
    factory: async_sessionmaker[AsyncSession]
    context: ToolContext
    scene_id: UUID
    shot_ids: list[UUID]
    asset_id: UUID
    other_project_id: UUID
    other_shot_id: UUID
    statements: list[str]


@pytest.fixture
async def world() -> AsyncIterator[World]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        actor = User(
            email="agent@example.com",
            display_name="Agent",
            password_hash="private-secret",
        )
        session.add(actor)
        await session.flush()
        workspace = Workspace(name="Owned", owner_user_id=actor.id)
        session.add(workspace)
        await session.flush()
        projects = [
            Project(workspace_id=workspace.id, name=name, aspect_ratio="16:9", budget_limit=0)
            for name in ("Culture", "Other")
        ]
        session.add_all(projects)
        await session.flush()
        episodes = [Episode(project_id=project.id, episode_number=1) for project in projects]
        session.add_all(episodes)
        await session.flush()
        scenes = [
            Scene(
                episode_id=episode.id, scene_number=1, location_name="Old bridge", time_of_day="day"
            )
            for episode in episodes
        ]
        session.add_all(scenes)
        await session.flush()
        shots = [
            Shot(
                project_id=projects[0].id,
                scene_id=scenes[0].id,
                shot_number=index,
                sort_order=index,
                visual_description=f"Bridge {index}",
                image_prompt="Documented stone bridge, no invented ornament.",
                video_prompt="Slow pan along the bridge.",
            )
            for index in (1, 2)
        ]
        other = Shot(
            project_id=projects[1].id,
            scene_id=scenes[1].id,
            shot_number=1,
            visual_description="Private other shot",
        )
        asset = Asset(
            project_id=projects[0].id,
            kind="character",
            name="Guide",
            description="Blue coat",
        )
        session.add_all([*shots, other, asset])
        await session.commit()
        context = ToolContext(
            actor_id=actor.id,
            workspace_id=workspace.id,
            project_id=projects[0].id,
            turn_id=uuid4(),
            thread_id=uuid4(),
            scope_type="project",
            scope_entity_id=projects[0].id,
        )
        statements: list[str] = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def record_statement(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        yield World(
            ToolExecutor(factory),
            factory,
            context,
            scenes[0].id,
            [shot.id for shot in shots],
            asset.id,
            projects[1].id,
            other.id,
            statements,
        )
    await engine.dispose()


async def test_reads_real_services_and_preserves_domain_rows(world: World) -> None:
    queries = [
        ("project_get", {}),
        ("scenes_list", {}),
        ("scene_get", {"scene_id": str(world.scene_id)}),
        ("shots_list", {"scene_id": str(world.scene_id)}),
        ("shot_get", {"shot_id": str(world.shot_ids[0])}),
        ("assets_list", {}),
        ("asset_get", {"asset_id": str(world.asset_id)}),
    ]
    for index, (name, arguments) in enumerate(queries):
        result = await world.executor.execute(
            name=name, arguments=arguments, call_id=f"call-{index}", context=world.context
        )
        assert result.ok, result.error
        assert result.call_id == f"call-{index}"
        assert len(result.result_hash) == 64
        assert result.observed_versions[f"project:{world.context.project_id}"] == 1
        assert "private-secret" not in result.model_dump_json()
        if name == "shot_get":
            assert result.data and result.data["image_prompt"] == (
                "Documented stone bridge, no invented ornament."
            )
            assert result.data["video_prompt"] == "Slow pan along the bridge."
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in world.statements
    )


async def test_model_can_correct_invalid_argument_then_page(world: World) -> None:
    invalid = await world.executor.execute(
        name="shots_list",
        arguments={"scene_id": str(world.scene_id), "execute": True},
        call_id="bad",
        context=world.context,
    )
    assert invalid.error and invalid.error.code == "ToolInputInvalid"
    assert invalid.call_id == "bad" and invalid.error.recoverable
    assert world.statements == []
    first = await world.executor.execute(
        name="shots_list",
        arguments={"scene_id": str(world.scene_id), "limit": 1},
        call_id="fixed",
        context=world.context,
    )
    assert first.data and first.data["next_offset"] == 1
    second = await world.executor.execute(
        name="shots_list",
        arguments={"scene_id": str(world.scene_id), "limit": 1, "offset": 1},
        call_id="page-2",
        context=world.context,
    )
    assert second.data and second.data["next_offset"] is None
    assert first.data["items"] != second.data["items"]


@pytest.mark.parametrize("replacement", ["actor_id", "workspace_id"])
async def test_actor_and_selected_workspace_rechecked(world: World, replacement: str) -> None:
    context = world.context.model_copy(update={replacement: uuid4()})
    result = await world.executor.execute(
        name="project_get", arguments={}, call_id="scope", context=context
    )
    assert not result.ok and result.data is None


async def test_foreign_project_and_narrow_shot_scope_do_not_disclose(world: World) -> None:
    result = await world.executor.execute(
        name="shot_get",
        arguments={"shot_id": str(world.other_shot_id)},
        call_id="foreign",
        context=world.context,
    )
    assert not result.ok and "Private other shot" not in result.model_dump_json()
    scope = world.context.model_copy(
        update={
            "scope_type": "shot",
            "scope_entity_id": world.shot_ids[0],
        }
    )
    result = await world.executor.execute(
        name="shot_get",
        arguments={"shot_id": str(world.shot_ids[1])},
        call_id="sibling",
        context=scope,
    )
    assert result.error and result.error.code == "ToolPermissionDenied"
    assert not result.error.recoverable and result.error.retry_class == "none"
    assert "shots_list" not in {spec.name for spec in ToolRegistry().specs(scope)}


@pytest.mark.parametrize("error_type", [ForbiddenError, UnauthorizedError])
async def test_permission_errors_are_not_parameter_corrections(world, monkeypatch, error_type):
    async def denied(self):
        raise error_type("private policy detail")

    monkeypatch.setattr(AgentReadService, "project", denied)
    result = await world.executor.execute(
        name="project_get", arguments={}, call_id="denied", context=world.context
    )
    assert not result.ok and result.data is None
    assert result.error.code == "ToolPermissionDenied"
    assert not result.error.recoverable and result.error.retry_class == "none"
    assert "private policy detail" not in result.model_dump_json()


async def test_changed_observed_version_requires_refresh(world: World) -> None:
    scope = world.context.model_copy(
        update={
            "expected_versions": {f"shot:{world.shot_ids[0]}": 2},
        }
    )
    result = await world.executor.execute(
        name="shot_get",
        arguments={"shot_id": str(world.shot_ids[0])},
        call_id="stale",
        context=scope,
    )
    assert result.error and result.error.code == "ContextStale"
    assert result.observed_versions[f"shot:{world.shot_ids[0]}"] == 1
    assert result.data is None and not result.error.recoverable


async def test_safe_exception_and_timeout(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(self):
        raise RuntimeError("postgresql://secret-password@host")

    monkeypatch.setattr(AgentReadService, "project", broken)
    result = await world.executor.execute(
        name="project_get", arguments={}, call_id="safe", context=world.context
    )
    assert result.error and result.error.code == "ToolExecutionFailed"
    assert "secret-password" not in result.model_dump_json()

    async def delayed(self):
        await asyncio.sleep(1)

    monkeypatch.setattr(AgentReadService, "project", delayed)
    scope = world.context.model_copy(
        update={
            "deadline": datetime.now(UTC) + timedelta(milliseconds=5),
        }
    )
    result = await world.executor.execute(
        name="project_get",
        arguments={},
        call_id="slow",
        context=scope,
    )
    assert result.error and result.error.code == "ToolTimeout"


async def test_large_result_is_not_silently_truncated(world: World) -> None:
    async with world.factory() as session:
        shot = await session.scalar(select(Shot).where(Shot.id == world.shot_ids[0]))
        assert shot
        shot.visual_description = "桥" * 12000
        await session.commit()
    result = await world.executor.execute(
        name="shot_get",
        arguments={"shot_id": str(world.shot_ids[0])},
        call_id="large",
        context=world.context,
    )
    assert result.truncated and not result.ok and result.data is None
    assert result.error and result.error.code == "ToolResultTooLarge"
    assert len(result.model_dump_json().encode()) < 32768


async def test_registry_specs_are_detached_and_deny_execution(world: World) -> None:
    registry = ToolRegistry()
    fingerprint = registry.fingerprint(world.context)
    spec = registry.specs()[0]
    spec.input_schema["properties"] = {"stolen": True}
    assert registry.fingerprint(world.context) == fingerprint
    assert registry.resolve("video_generate", world.context) is None
    assert all(tool["type"] == "function" for tool in registry.openai_tools())


async def _thread(world: World, session: AsyncSession) -> None:
    session.add(
        DirectorThread(
            id=world.context.thread_id,
            project_id=world.context.project_id,
            scope_type=world.context.scope_type,
            scope_entity_id=world.context.scope_entity_id,
            created_by=world.context.actor_id,
        )
    )
    await session.flush()


async def test_prompt_proposal_is_pending_and_leaves_shot_unchanged(world: World) -> None:
    async with world.factory() as session:
        await _thread(world, session)
        original = await session.get(Shot, world.shot_ids[0])
        assert original is not None
        original_prompt = original.image_prompt
        result = await create_agent_shot_proposal(
            session,
            context=world.context,
            call_id="propose-1",
            arguments={
                "shot_id": str(world.shot_ids[0]),
                "expected_version": 1,
                "image_prompt": "Use the documented stone bridge structure.",
                "rationale": "Preserve the reference architecture.",
            },
        )
        proposal = await session.get(DirectorProposal, result.proposal_ids[0])
        item = await session.scalar(
            select(DirectorProposalItem).where(
                DirectorProposalItem.proposal_id == result.proposal_ids[0],
            )
        )
        shot = await session.get(Shot, world.shot_ids[0])
        assert proposal and proposal.status == "pending"
        assert item and item.command == "shot.update_image_prompt" and item.status == "pending"
        assert item.expected_target_version == 1
        assert shot and shot.image_prompt == original_prompt and shot.version == 1
        assert result.requires_apply and result.observed_versions[f"shot:{shot.id}"] == 1
        await session.rollback()
    async with world.factory() as session:
        assert await session.get(DirectorProposal, result.proposal_ids[0]) is None


async def test_proposal_requires_current_version_and_scope(world: World) -> None:
    async with world.factory() as session:
        await _thread(world, session)
        with pytest.raises(ConflictError):
            await create_agent_shot_proposal(
                session,
                context=world.context,
                call_id="stale",
                arguments={
                    "shot_id": str(world.shot_ids[0]),
                    "expected_version": 2,
                    "video_prompt": "A gentle pan.",
                    "rationale": "Improve flow.",
                },
            )
        wrong_context = world.context.model_copy(
            update={
                "scope_type": "shot",
                "scope_entity_id": world.shot_ids[0],
            }
        )
        with pytest.raises(ValidationAppError):
            await create_agent_shot_proposal(
                session,
                context=wrong_context,
                call_id="scope",
                arguments={
                    "shot_id": str(world.shot_ids[1]),
                    "expected_version": 1,
                    "video_prompt": "A gentle pan.",
                    "rationale": "Improve flow.",
                },
            )
        assert list(await session.scalars(select(DirectorProposal))) == []


@pytest.mark.parametrize(
    "prompts",
    [
        {},
        {"image_prompt": "a", "video_prompt": "b"},
        {"image_prompt": " "},
        {"video_prompt": "a", "apply": True},
    ],
)
def test_proposal_schema_rejects_ambiguous_or_executable_input(prompts: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ShotPromptProposalInput.model_validate(
            {
                "shot_id": str(uuid4()),
                "expected_version": 1,
                "rationale": "reason",
                **prompts,
            }
        )


async def test_standalone_read_executor_cannot_write_proposals(world: World) -> None:
    result = await world.executor.execute(
        name="shot_prompt_propose",
        arguments={
            "shot_id": str(world.shot_ids[0]),
            "expected_version": 1,
            "image_prompt": "A bridge.",
            "rationale": "Reason.",
        },
        call_id="proposal",
        context=world.context,
    )
    assert result.error and result.error.code == "ToolTransactionRequired"
    assert world.statements == []
