"""Proposal decisions commit independently of director recovery."""

from uuid import uuid4

import pytest
from app.access.models import ProjectCreativeProfile
from app.assets.models import Shot
from app.director.assistant_models import DirectorThread
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.inbox import receive_production_event
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.director.wakeup import process_director_wakeup
from app.events.models import OutboxEvent
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed, _seed_video_shot


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["accepted", "rejected"])
async def test_proposal_decision_rollback_replay_and_independent_delivery(monkeypatch, decision):
    dbname = f"dramaforge_d2_proposal_{uuid4().hex[:8]}"
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
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            before_prompt, before_version = shot.video_prompt, shot.version
            session.add(ProjectCreativeProfile(
                project_id=project.id, start_type="FREE", director_autonomy="ASSIST",
            ))
            thread = DirectorThread(project_id=project.id, scope_type="shot",
                                    scope_entity_id=shot.id, created_by=actor.id)
            session.add(thread)
            await session.flush()
            proposal = DirectorProposal(project_id=project.id, thread_id=thread.id,
                                        scope_type="shot", scope_entity_id=shot.id,
                                        created_by=actor.id)
            session.add(proposal)
            await session.flush()
            item = DirectorProposalItem(
                project_id=project.id, proposal_id=proposal.id,
                command="shot.update_video_prompt",
                payload={"shot_id": str(shot.id), "video_prompt": "Explicitly selected"},
                expected_target_version=shot.version,
            )
            turn = DirectorTurn(
                project_id=project.id, workspace_id=project.workspace_id, actor_id=actor.id,
                scope_type="shot", scope_entity_id=shot.id, request_key="decision",
                context_hash="a" * 64, status="awaiting_user", proposal_id=proposal.id,
                step_count=1, request_summary={"max_steps": 4},
            )
            session.add_all([item, turn])
            await session.commit()
        body = PartialApplyInput(decisions=[ProposalDecision(item_id=item.id, decision=decision)])
        original = DirectorBusinessCheckpoints.__init__

        def unavailable(*args, **kwargs):
            raise RuntimeError("Director unavailable")

        monkeypatch.setattr(DirectorBusinessCheckpoints, "__init__", unavailable)
        for commit in (False, True, True):
            async with factory() as session:
                await set_rls_context(session, user_id=actor.id,
                                      workspace_id=project.workspace_id, project_id=project.id)
                result = await ProposalService(session, actor=actor).partial_apply(
                    project=project, proposal_id=proposal.id, apply_input=body,
                )
                assert not result.failed
                if commit:
                    await session.commit()
                else:
                    await session.rollback()
            async with admin() as session:
                saved = await session.get(Shot, shot.id)
                notices = (await session.scalars(select(OutboxEvent).where(
                    OutboxEvent.topic == "production.facts.v1",
                ))).all()
                assert len(notices) == int(commit)
                assert saved.video_prompt == (
                    "Explicitly selected" if commit and decision == "accepted" else before_prompt
                )
                assert saved.version == before_version + int(commit and decision == "accepted")
                assert (await session.get(DirectorTurn, turn.id)).status == "awaiting_user"
        async with factory() as session:
            await set_rls_context(session, user_id=actor.id,
                                  workspace_id=project.workspace_id, project_id=project.id)
            if decision == "rejected":
                with pytest.raises(ConflictError) as rejected:
                    await DirectorTurnService(session).assert_context_not_rejected(
                        project_id=project.id, context_hash=turn.context_hash,
                    )
                assert rejected.value.details["code"] == "DIRECTOR_CONTEXT_REJECTED"
            inbox_id = await receive_production_event(
                session, project_id=project.id, event_id=notices[0].event_id,
            )
            await session.commit()
        monkeypatch.setattr(DirectorBusinessCheckpoints, "__init__", original)
        assert await process_director_wakeup(factory, inbox_id=inbox_id)
        assert not await process_director_wakeup(factory, inbox_id=inbox_id)
        async with admin() as session:
            saved_turn = await session.get(DirectorTurn, turn.id)
            assert saved_turn.status == ("completed" if decision == "rejected" else "awaiting_user")
            assert saved_turn.wait_reason == (
                "proposal_rejected" if decision == "rejected" else "accepted_changes_review"
            )
            if decision == "accepted":
                action = saved_turn.response_summary["coordination"]["current_action"]
                assert action["requires_confirmation"] is True
                assert action["accepted_item_ids"] == [str(item.id)]
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
