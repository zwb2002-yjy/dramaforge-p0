"""Real invocation identity, transition, replay and tenant boundaries."""

import asyncio
from uuid import uuid4

import pytest
from app.director.invocation_models import DirectorInvocation
from app.director.invocations import InvocationService
from app.director.text_transport import DirectorTextTransport
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.providers.contracts.common import ExecutionContext, ProviderCreateResult
from app.providers.contracts.text import TextGenerateRequest
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed


class Suggestion(BaseModel):
    text: str


class NeverTextModel:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        request: TextGenerateRequest,
        model_id: str,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        self.calls += 1
        raise AssertionError((request, model_id, context))


@pytest.mark.asyncio
async def test_invocation_identity_unknown_response_and_verified_result_survive_sessions():
    dbname = f"dramaforge_d3_invocation_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, _binding, actor = await _seed(session)
            await session.commit()
            other, _other_binding, other_actor = await _seed(session)
            turn = DirectorTurn(
                project_id=project.id, workspace_id=project.workspace_id, actor_id=actor.id,
                scope_type="shot", scope_entity_id=uuid4(), request_key="invocation-test",
                context_hash="a" * 64,
            )
            session.add(turn)
            await session.commit()
        args = dict(
            project_id=project.id, turn_id=turn.id, invocation_key="step:1:primary:1",
            step_key="step:1:primary", attempt=1,
            model_resolution={"model_id": "test-model", "binding_revision": 1},
            request_snapshot={"prompt": "A bounded suggestion"},
            output_schema=Suggestion.model_json_schema(mode="validation"), intent_version="v1",
        )

        async def scope(session):
            await set_rls_context(session, user_id=actor.id,
                                  workspace_id=project.workspace_id, project_id=project.id)

        async def prepare():
            async with factory() as session:
                await scope(session)
                row = await InvocationService(session).prepare(**args)
                await session.commit()
                return row.id

        first, second = await asyncio.gather(prepare(), prepare())
        assert first == second
        async with factory() as session:
            await scope(session)
            with pytest.raises(ConflictError):
                await InvocationService(session).prepare(**{
                    **args, "request_snapshot": {"prompt": "Changed"},
                })
            await session.rollback()

        async def start():
            async with factory() as session:
                await scope(session)
                accepted = await InvocationService(session).start(
                    project_id=project.id, invocation_id=first,
                )
                await session.commit()
                return accepted

        assert sorted(await asyncio.gather(start(), start())) == [False, True]
        async with factory() as session:
            await scope(session)
            await InvocationService(session).mark_unknown(
                project_id=project.id, invocation_id=first,
            )
            await session.commit()
        assert not await start()
        async with factory() as session:
            await scope(session)
            row = await InvocationService(session).complete(
                project_id=project.id, invocation_id=first, output=Suggestion(text="Verified"),
                token_usage={"prompt_tokens": 10},
            )
            assert row.cost_status == "unknown" and row.reported_cost is None
            await session.commit()
        assert await prepare() == first
        assert not await start()
        async with factory() as session:
            await scope(session)
            journal = InvocationService(session)
            restored = await journal.get(project_id=project.id, invocation_id=first)
            assert restored.validated_output == {"text": "Verified"}
            with pytest.raises(ConflictError):
                await journal.complete(
                    project_id=project.id, invocation_id=first, output=Suggestion(text="Changed"),
                    token_usage={"prompt_tokens": 10},
                )
            await session.rollback()
        for invalid in ({"status": "prepared"}, {"cost_status": "reported"}):
            async with factory() as session:
                await scope(session)
                with pytest.raises(IntegrityError):
                    await session.execute(update(DirectorInvocation).where(
                        DirectorInvocation.id == first,
                    ).values(**invalid))
                await session.rollback()
        async with factory() as session:
            await set_rls_context(session, user_id=other_actor.id,
                                  workspace_id=other.workspace_id, project_id=other.id)
            assert await session.scalar(select(DirectorInvocation)) is None
            with pytest.raises(NotFoundError):
                await InvocationService(session).get(project_id=project.id, invocation_id=first)
            result = await session.execute(update(DirectorInvocation).where(
                DirectorInvocation.id == first,
            ).values(status="failed"))
            assert result.rowcount == 0
            await session.rollback()
        # Even a privileged insert cannot attach a project's invocation to a
        # different project's turn: the composite foreign key is authoritative.
        async with admin() as session:
            bad = DirectorInvocation(
                **{**args, "project_id": other.id, "invocation_key": "forged"},
                input_hash="b" * 64,
            )
            session.add(bad)
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.asyncio
async def test_transport_recovers_completed_journal_and_never_replays_uncertain_submission():
    dbname = f"dramaforge_d3_transport_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, _binding, actor = await _seed(session)
            await session.commit()

        async def scope(session):
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )

        async def make_turn(session, *, request_key: str):
            scope_entity_id = uuid4()
            context_payload = {"shot": "frozen"}
            intent_snapshot = {"request": "bounded"}
            input_versions = {"shot": 1}
            turn, created = await DirectorTurnService(session).create_or_get(
                project=project,
                actor=actor,
                scope_type="shot",
                scope_entity_id=scope_entity_id,
                request_key=request_key,
                context_snapshot={
                    "workspace_id": str(project.workspace_id),
                    "project_id": str(project.id),
                    "scope_type": "shot",
                    "scope_entity_id": str(scope_entity_id),
                    "slot": str(ModelSlot.PLANNING_STORYBOARD),
                    "input_versions": input_versions,
                    "intent": intent_snapshot,
                    "context": context_payload,
                },
                input_versions=input_versions,
                intent_snapshot=intent_snapshot,
                max_steps=4,
            )
            assert created
            await DirectorTurnService(session).claim(
                project_id=project.id,
                turn_id=turn.id,
                expected_revision=turn.revision,
            )
            turn.model_resolution = {
                "slot": str(ModelSlot.PLANNING_STORYBOARD),
                "model_id": "test/director",
                "model_binding_ref": "test/director:planning.storyboard",
            }
            turn.transport_status = "prepared"
            return turn, scope_entity_id, context_payload, intent_snapshot, input_versions

        async with factory() as session:
            await scope(session)
            turn, entity_id, context, intent, versions = await make_turn(
                session, request_key="transport:completed",
            )
            await session.commit()
            await scope(session)
            invocation = await InvocationService(session).prepare(
                project_id=project.id,
                turn_id=turn.id,
                invocation_key="text:primary:1",
                step_key="text:primary",
                attempt=1,
                model_resolution=dict(turn.model_resolution),
                request_snapshot={"prompt": "frozen"},
                output_schema=Suggestion.model_json_schema(mode="validation"),
                intent_version="intent-v1",
            )
            await session.commit()
            await scope(session)
            assert await InvocationService(session).start(
                project_id=project.id, invocation_id=invocation.id,
            )
            await session.commit()
            await scope(session)
            completed = await InvocationService(session).complete(
                project_id=project.id,
                invocation_id=invocation.id,
                output=Suggestion(text="Recovered"),
                token_usage={"total_tokens": 9},
            )
            completed.response_summary = {
                "request_id": "persisted-call",
                "litellm_model_name": "upstream/director-v1",
                "output_text_hash": completed.output_hash,
            }
            await session.commit()

            never = NeverTextModel()
            await scope(session)
            restored = await DirectorTextTransport(
                session,
                registry=ModelRegistry(),
                text_model=never,
            ).generate_structured(
                project=project,
                actor=actor,
                scope_type="shot",
                scope_entity_id=entity_id,
                request_key="transport:completed",
                slot=ModelSlot.PLANNING_STORYBOARD,
                task_name="recovery_test",
                system_instruction="Return the bounded result.",
                input_versions=versions,
                intent_snapshot=intent,
                context_payload=context,
                output_type=Suggestion,
            )
            assert restored.value.text == "Recovered"
            assert restored.evidence.actual_model == "upstream/director-v1"
            assert never.calls == 0

            await scope(session)
            uncertain_turn, entity_id, context, intent, versions = await make_turn(
                session, request_key="transport:uncertain",
            )
            await session.commit()
            await scope(session)
            uncertain = await InvocationService(session).prepare(
                project_id=project.id,
                turn_id=uncertain_turn.id,
                invocation_key="text:primary:1",
                step_key="text:primary",
                attempt=1,
                model_resolution=dict(uncertain_turn.model_resolution),
                request_snapshot={"prompt": "uncertain"},
                output_schema=Suggestion.model_json_schema(mode="validation"),
                intent_version="intent-v1",
            )
            await session.commit()
            await scope(session)
            assert await InvocationService(session).start(
                project_id=project.id, invocation_id=uncertain.id,
            )
            await session.commit()

            await scope(session)
            with pytest.raises(ValidationAppError) as raised:
                await DirectorTextTransport(
                    session,
                    registry=ModelRegistry(),
                    text_model=never,
                ).generate_structured(
                    project=project,
                    actor=actor,
                    scope_type="shot",
                    scope_entity_id=entity_id,
                    request_key="transport:uncertain",
                    slot=ModelSlot.PLANNING_STORYBOARD,
                    task_name="recovery_test",
                    system_instruction="Return the bounded result.",
                    input_versions=versions,
                    intent_snapshot=intent,
                    context_payload=context,
                    output_type=Suggestion,
                )
            assert raised.value.details["code"] == "DIRECTOR_TEXT_CALL_UNKNOWN"
            assert never.calls == 0
            await scope(session)
            saved_uncertain = await InvocationService(session).get(
                project_id=project.id, invocation_id=uncertain.id,
            )
            saved_turn = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=uncertain_turn.id,
            )
            assert saved_uncertain.status == "unknown_submission"
            assert saved_turn.status == "failed"
            assert saved_turn.transport_status == "unknown_submission"
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
