"""Research and knowledge decisions emit one safe domain event per accepted decision."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.knowledge import KnowledgeService
from app.assets.knowledge_references import KnowledgeReferenceService
from app.assets.research import ResearchService
from app.events.models import EventLog
from sqlalchemy import select


@pytest.fixture
async def world(session):
    owner = User(email=f"evt-{uuid4()}@example.com", display_name="E", password_hash="x")
    session.add(owner)
    await session.flush()
    workspace = Workspace(name="Events", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    return {"session": session, "owner": owner, "workspace": workspace, "project": project}


async def _events(session) -> list[EventLog]:
    return list(await session.scalars(select(EventLog).order_by(EventLog.occurred_at)))


async def test_research_and_knowledge_decisions_emit_safe_events(world):
    session = world["session"]
    research = ResearchService(session, actor=world["owner"], project_id=world["project"].id)
    created = await research.create_result(
        kind="person",
        body={"schema_version": 1, "display_name": "张某"},
        verification="unverified",
        citations=[],
        request_key="evt-research-1",
    )
    await research.append_revision(
        created.result_id,
        expected_version=created.result_version,
        base_revision_id=created.revision_id,
        body={"schema_version": 1, "display_name": "张某", "description": "修订"},
        verification="user_asserted",
        citations=[],
        request_key="evt-research-2",
    )
    knowledge = KnowledgeService(session, actor=world["owner"])
    entry = await knowledge.create_entry(
        workspace_id=world["workspace"].id,
        kind="person",
        title="古桥匠人",
        body={"schema_version": 1, "display_name": "张某"},
        allowed_uses=["research"],
        public_source_notes=[],
        source_links=[],
        operation="publish",
        request_key="evt-knowledge-1",
    )
    references = KnowledgeReferenceService(
        session, actor=world["owner"], project_id=world["project"].id
    )
    reference, _created = await references.create(
        knowledge_entry_id=entry.entry_id,
        knowledge_revision_id=entry.revision_id,
        allowed_use="research",
    )
    await references.patch(reference.id, expected_version=1, attached=False)
    await knowledge.withdraw(
        entry.entry_id, expected_version=entry.result_entry_version, request_key="evt-knowledge-2"
    )
    await session.commit()

    events = await _events(session)
    types = [event.event_type for event in events]
    assert types == [
        "research.result.created",
        "research.result.revised",
        "knowledge.entry.published",
        "knowledge.reference.attached",
        "knowledge.reference.detached",
        "knowledge.entry.withdrawn",
    ]
    for event in events:
        text = str(event.payload)
        for forbidden in ("object_key", "quoted_text", "source_fragment", "credential"):
            assert forbidden not in text
    created_event = events[0]
    assert created_event.aggregate_type == "ResearchResult"
    assert created_event.project_id == world["project"].id
    assert created_event.payload["kind"] == "person"
    knowledge_event = events[2]
    assert knowledge_event.project_id is None
    assert knowledge_event.aggregate_type == "KnowledgeEntry"
    assert knowledge_event.payload["publication_status"] == "published"
