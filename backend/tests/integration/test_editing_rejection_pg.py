"""R7 acceptance gap: Editing rejection is persistent, scoped and no-cost."""

from __future__ import annotations

from app.api.v1.editing import EditingSuggestionRejectBody, reject_editing_suggestion
from app.director.assistant_models import DirectorThread
from app.director.inbox import receive_production_event
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.director.wakeup import process_director_wakeup
from app.editing.models import EditSession
from app.events.models import OutboxEvent
from app.execution.models import NodeRun, ProviderOperation
from app.shared.db import set_rls_context
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import _project
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


async def test_editing_rejection_survives_restart_and_replays_without_mutation(pg_session):
    db = pg_session
    user, project_id, workspace_id = await _project(db)
    edit = EditSession(
        project_id=project_id,
        name="Rejected edit",
        version=1,
        timeline={"clips": [], "metadata": {}},
        production_lineage={},
        created_by=user.id,
    )
    thread = DirectorThread(
        project_id=project_id,
        scope_type="project",
        scope_entity_id=project_id,
        title="Editing",
        created_by=user.id,
    )
    db.add_all([edit, thread])
    await db.flush()
    proposal = DirectorProposal(
        project_id=project_id,
        thread_id=thread.id,
        scope_type="edit_session",
        scope_entity_id=edit.id,
        created_by=user.id,
        status="pending",
    )
    db.add(proposal)
    await db.flush()
    item = DirectorProposalItem(
        project_id=project_id,
        proposal_id=proposal.id,
        command="edit_session.apply_timeline_plan",
        payload={"edit_session_id": str(edit.id), "plan": {"operations": []}},
        expected_target_version=1,
        status="pending",
    )
    turn = DirectorTurn(
        project_id=project_id,
        workspace_id=workspace_id,
        actor_id=user.id,
        scope_type="edit_session",
        scope_entity_id=edit.id,
        request_key="editing-rejection-pg",
        context_hash="e" * 64,
        proposal_id=proposal.id,
        status="awaiting_user",
        step_count=1,
    )
    db.add_all([item, turn])
    await db.commit()
    result = await reject_editing_suggestion(
        project_id=project_id,
        session_id=edit.id,
        proposal_id=proposal.id,
        body=EditingSuggestionRejectBody(expected_session_version=1),
        user=user,
        session=db,
        _csrf="controlled",
    )
    assert result.status == "rejected"
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as before_delivery:
        await before_delivery.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            before_delivery, user_id=user.id, workspace_id=workspace_id, project_id=project_id
        )
        persisted = await before_delivery.get(DirectorTurn, turn.id)
        assert persisted is not None and persisted.status == "awaiting_user"
        notice = await before_delivery.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.topic == "production.facts.v1")
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.event_id.desc())
        )
        assert notice is not None
        inbox_id = await receive_production_event(
            before_delivery, project_id=project_id, event_id=notice.event_id,
        )
        await before_delivery.commit()

    assert await process_director_wakeup(factory, inbox_id=inbox_id)
    async with factory() as reader:
        await reader.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            reader, user_id=user.id, workspace_id=workspace_id, project_id=project_id
        )
        persisted = await reader.get(DirectorTurn, turn.id)
        assert persisted.status == "completed" and persisted.wait_reason == "proposal_rejected"
        assert (await reader.get(DirectorProposalItem, item.id)).status == "rejected"
        assert (await reader.get(EditSession, edit.id)).version == 1
        assert await reader.scalar(select(func.count()).select_from(NodeRun)) == 0
        assert await reader.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        revision = persisted.revision
    replay = await reject_editing_suggestion(
        project_id=project_id,
        session_id=edit.id,
        proposal_id=proposal.id,
        body=EditingSuggestionRejectBody(expected_session_version=1),
        user=user,
        session=db,
        _csrf="controlled",
    )
    assert replay == result
    await db.refresh(turn)
    assert turn.revision == revision
