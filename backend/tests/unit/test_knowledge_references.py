"""Project fixed knowledge references: pin, detach/reattach and availability (I4-03)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.knowledge import KnowledgeService
from app.assets.knowledge_references import (
    KnowledgeReferenceConflictError,
    KnowledgeReferenceService,
)
from app.shared.errors import NotFoundError


@pytest.fixture
async def references(session):
    owner = User(email=f"ref-{uuid4()}@example.com", display_name="R", password_hash="x")
    session.add(owner)
    await session.flush()
    workspace = Workspace(name="Refs", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    knowledge = KnowledgeService(session, actor=owner)
    created = await knowledge.create_entry(
        workspace_id=workspace.id,
        kind="person",
        title="古桥匠人",
        body={"schema_version": 1, "display_name": "张某"},
        allowed_uses=["research", "creation"],
        public_source_notes=[],
        source_links=[],
        operation="publish",
        request_key="ref-publish-1",
    )
    return {
        "session": session,
        "owner": owner,
        "workspace": workspace,
        "project": project,
        "knowledge": knowledge,
        "entry_id": created.entry_id,
        "revision_id": created.revision_id,
        "service": KnowledgeReferenceService(
            session, actor=owner, project_id=project.id
        ),
    }


async def test_reference_pin_detach_reattach_and_availability(references):
    service = references["service"]
    created, is_new = await service.create(
        knowledge_entry_id=references["entry_id"],
        knowledge_revision_id=references["revision_id"],
        allowed_use="research",
    )
    assert is_new is True and created.availability == "published"
    replay, is_new = await service.create(
        knowledge_entry_id=references["entry_id"],
        knowledge_revision_id=references["revision_id"],
        allowed_use="research",
    )
    assert is_new is False and replay.id == created.id
    detached = await service.patch(created.id, expected_version=1, attached=False)
    assert detached.version == 2 and detached.detached_at is not None
    active, total = await service.list(active=True)
    assert active == [] and total == 0
    again, is_new = await service.create(
        knowledge_entry_id=references["entry_id"],
        knowledge_revision_id=references["revision_id"],
        allowed_use="research",
    )
    assert is_new is False and again.detached_at is not None
    reattached = await service.patch(created.id, expected_version=2, attached=True)
    assert reattached.version == 3 and reattached.detached_at is None
    with pytest.raises(KnowledgeReferenceConflictError) as stale:
        await service.patch(created.id, expected_version=1, attached=False)
    assert stale.value.code == "KNOWLEDGE_REFERENCE_STALE_VERSION"
    # A new publish that narrows uses marks the old fixed reference restricted.
    await references["knowledge"].append_revision(
        references["entry_id"],
        expected_version=2,
        title="古桥匠人",
        body={"schema_version": 1, "display_name": "张某", "description": "修订"},
        allowed_uses=["creation"],
        public_source_notes=[],
        source_links=[],
        operation="publish",
        request_key="ref-publish-2",
    )
    rows, total = await service.list(active=True)
    assert total == 1 and rows[0].availability == "restricted"
    # The same natural key stays one reference; it now reports restricted.
    replay, is_new = await service.create(
        knowledge_entry_id=references["entry_id"],
        knowledge_revision_id=references["revision_id"],
        allowed_use="research",
    )
    assert is_new is False and replay.availability == "restricted"
    with pytest.raises(NotFoundError):
        await service.create(
            knowledge_entry_id=uuid4(),
            knowledge_revision_id=references["revision_id"],
            allowed_use="research",
        )


async def test_reference_rejects_draft_or_withdrawn_knowledge(references):
    service = references["service"]
    knowledge = references["knowledge"]
    draft = await knowledge.create_entry(
        workspace_id=references["workspace"].id,
        kind="summary",
        title="草稿",
        body={"schema_version": 1, "text": "草稿内容"},
        allowed_uses=["research"],
        public_source_notes=[],
        source_links=[],
        operation="save_draft",
        request_key="ref-draft-1",
    )
    with pytest.raises(KnowledgeReferenceConflictError) as draft_error:
        await service.create(
            knowledge_entry_id=draft.entry_id,
            knowledge_revision_id=draft.revision_id,
            allowed_use="research",
        )
    assert draft_error.value.code == "KNOWLEDGE_NOT_PUBLISHED"
    created, is_new = await service.create(
        knowledge_entry_id=references["entry_id"],
        knowledge_revision_id=references["revision_id"],
        allowed_use="creation",
    )
    assert is_new is True and created.availability == "published"
    await knowledge.withdraw(
        references["entry_id"], expected_version=2, request_key="ref-withdraw-1"
    )
    rows, total = await service.list(active=True)
    assert total == 1 and rows[0].availability == "withdrawn"
    with pytest.raises(KnowledgeReferenceConflictError) as withdrawn:
        await service.create(
            knowledge_entry_id=references["entry_id"],
            knowledge_revision_id=references["revision_id"],
            allowed_use="research",
        )
    assert withdrawn.value.code == "KNOWLEDGE_NOT_PUBLISHED"
