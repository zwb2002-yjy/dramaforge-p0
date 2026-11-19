"""Owner-scoped knowledge drafts, publication, withdrawal and private provenance."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.knowledge import (
    KnowledgeConflictError,
    KnowledgeService,
    PublicSourceNote,
    SourceLinkInput,
)
from app.assets.research import ResearchService
from app.shared.errors import NotFoundError, ValidationAppError


@pytest.fixture
async def knowledge(session):
    owner = User(email=f"know-{uuid4()}@example.com", display_name="K", password_hash="x")
    session.add(owner)
    await session.flush()
    workspace = Workspace(name="Knowledge", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    research = ResearchService(session, actor=owner, project_id=project.id)
    result = await research.create_result(
        kind="person",
        body={"schema_version": 1, "display_name": "张某"},
        verification="unverified",
        citations=[],
        request_key="know-research",
    )
    return {
        "session": session,
        "owner": owner,
        "workspace": workspace,
        "project": project,
        "research": result,
        "service": KnowledgeService(session, actor=owner),
    }


def _entry_payload(**overrides):
    payload = {
        "workspace_id": None,
        "kind": "person",
        "title": "古桥匠人",
        "body": {"schema_version": 1, "display_name": "张某", "description": "明代匠人"},
        "allowed_uses": ["research", "creation"],
        "public_source_notes": [PublicSourceNote(label="地方志")],
        "source_links": [],
        "operation": "save_draft",
        "request_key": "know-create-1",
    }
    payload.update(overrides)
    return payload


async def test_draft_publish_withdraw_lifecycle(knowledge):
    service = knowledge["service"]
    payload = _entry_payload(workspace_id=knowledge["workspace"].id)
    draft = await service.create_entry(**payload)
    assert draft.result_entry_version == 2 and draft.publication_status == "draft"
    replay = await service.create_entry(**payload)
    assert replay.revision_id == draft.revision_id
    with pytest.raises(KnowledgeConflictError) as reused:
        await service.create_entry(**{**payload, "title": "不同标题"})
    assert reused.value.code == "KNOWLEDGE_REQUEST_KEY_REUSED"
    published = await service.append_revision(
        draft.entry_id,
        expected_version=2,
        title="古桥匠人",
        body={"schema_version": 1, "display_name": "张某", "description": "明代匠人（修订）"},
        allowed_uses=["research"],
        public_source_notes=[],
        source_links=[],
        operation="publish",
        request_key="know-publish-1",
    )
    assert published.result_entry_version == 3 and published.publication_status == "published"
    with pytest.raises(KnowledgeConflictError) as published_conflict:
        await service.append_revision(
            draft.entry_id,
            expected_version=3,
            title="草稿",
            body={"schema_version": 1, "display_name": "张某"},
            allowed_uses=["research"],
            public_source_notes=[],
            source_links=[],
            operation="save_draft",
            request_key="know-draft-after-publish",
        )
    assert published_conflict.value.code == "KNOWLEDGE_PUBLISHED_REQUIRES_PUBLISH"
    with pytest.raises(KnowledgeConflictError) as stale:
        await service.append_revision(
            draft.entry_id,
            expected_version=2,
            title="迟到",
            body={"schema_version": 1, "display_name": "张某"},
            allowed_uses=["research"],
            public_source_notes=[],
            source_links=[],
            operation="publish",
            request_key="know-stale",
        )
    assert stale.value.code == "KNOWLEDGE_STALE_VERSION"
    withdrawn = await service.withdraw(
        draft.entry_id, expected_version=3, request_key="know-withdraw-1"
    )
    assert withdrawn.result_entry_version == 4
    assert withdrawn.publication_status == "withdrawn"
    entry = await service.read_entry(draft.entry_id)
    assert entry.withdrawn_at is not None
    revisions, total = await service.list_revisions(draft.entry_id)
    assert total == 3 and [row.operation for row in revisions] == [
        "withdraw", "publish", "save_draft",
    ]
    published_rows, total = await service.list_entries(status="published")
    assert total == 0
    withdrawn_rows, total = await service.list_entries(status="withdrawn")
    assert total == 1 and withdrawn_rows[0].id == draft.entry_id


async def test_private_source_links_require_the_originating_project(knowledge):
    service = knowledge["service"]
    created = await service.create_entry(
        **_entry_payload(
            workspace_id=knowledge["workspace"].id,
            source_links=[
                SourceLinkInput(
                    project_id=knowledge["project"].id,
                    research_revision_id=knowledge["research"].revision_id,
                )
            ],
        )
    )
    links = await service.source_links(
        created.revision_id, project_id=knowledge["project"].id
    )
    assert len(links) == 1
    assert links[0].research_revision_id == knowledge["research"].revision_id
    other_project = Project(
        workspace_id=knowledge["workspace"].id,
        name="Other",
        aspect_ratio="16:9",
        budget_limit=0,
    )
    knowledge["session"].add(other_project)
    await knowledge["session"].flush()
    assert await service.source_links(created.revision_id, project_id=other_project.id) == []
    with pytest.raises(NotFoundError):
        await service.source_links(created.revision_id, project_id=uuid4())


async def test_validation_rejects_unknown_uses_notes_and_foreign_sources(knowledge):
    service = knowledge["service"]
    with pytest.raises(ValidationAppError) as use:
        await service.create_entry(
            **_entry_payload(
                workspace_id=knowledge["workspace"].id, allowed_uses=["unknown_use"]
            )
        )
    assert use.value.details["code"] == "KNOWLEDGE_USE_INVALID"
    with pytest.raises(ValidationAppError) as note:
        await service.create_entry(
            **_entry_payload(
                workspace_id=knowledge["workspace"].id,
                public_source_notes=[PublicSourceNote(label="x", public_url="ftp://bad")],
            )
        )
    assert note.value.details["code"] == "KNOWLEDGE_NOTE_URL_INVALID"
    other = User(email=f"other-{uuid4()}@example.com", display_name="O", password_hash="x")
    knowledge["session"].add(other)
    await knowledge["session"].flush()
    foreign_workspace = Workspace(name="Foreign", owner_user_id=other.id)
    knowledge["session"].add(foreign_workspace)
    await knowledge["session"].flush()
    foreign_project = Project(
        workspace_id=foreign_workspace.id, name="F", aspect_ratio="16:9", budget_limit=0
    )
    knowledge["session"].add(foreign_project)
    await knowledge["session"].flush()
    with pytest.raises(ValidationAppError) as foreign:
        await service.create_entry(
            **_entry_payload(
                workspace_id=knowledge["workspace"].id,
                source_links=[
                    SourceLinkInput(
                        project_id=foreign_project.id,
                        research_revision_id=knowledge["research"].revision_id,
                    )
                ],
            )
        )
    assert foreign.value.details["code"] == "KNOWLEDGE_SOURCE_FORBIDDEN"
