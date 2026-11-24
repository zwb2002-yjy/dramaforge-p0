"""Authorize the selected immutable research revision for a project Director discussion."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_admission import AdmissionDecision, EgressAdmission
from app.access.models import Project, User
from app.assets.knowledge_references import KnowledgeReferenceService
from app.assets.research_models import ResearchResult, ResearchResultRevision
from app.assets.research_source_access import research_source_permissions
from app.contracts.agent import AgentMessage, AgentToolCall
from app.director.text_transport import research_model_identity
from app.shared.errors import ValidationAppError


class ResearchDiscussionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result_id: UUID
    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeDiscussionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_id: UUID
    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


async def read_discussion(
    session: AsyncSession,
    project: Project,
    ref: ResearchDiscussionRef | KnowledgeDiscussionRef,
    resolution: dict[str, Any],
    *,
    actor_id: UUID,
    expected: dict[str, object] | None = None,
) -> tuple[dict[str, object], AdmissionDecision, str | None]:
    """The project, research head and cited-file locks are held through submission."""
    await session.scalar(
        select(Project.id).where(Project.id == project.id).with_for_update(read=True)
    )
    head: str | None
    grants: dict[str, str] | None
    public_body = None
    if isinstance(ref, KnowledgeDiscussionRef):
        actor = await session.get(User, actor_id)
        if actor is None:
            raise ValidationAppError("用户不可用")
        eligibility, public_body = await KnowledgeReferenceService(
            session, actor=actor, project_id=project.id
        ).discussion_snapshot(ref.reference_id, ref.revision_id, ref.content_hash)
        # Consumer-side evidence stores only the hash; private source mappings stay private.
        grants = {
            "eligibility_hash": hashlib.sha256(
                json.dumps(eligibility, sort_keys=True).encode()
            ).hexdigest()
        }
        head = "published_knowledge"
    else:
        head = await session.scalar(
            select(ResearchResult.kind)
            .join(
                ResearchResultRevision,
                ResearchResult.current_revision_id == ResearchResultRevision.id,
            )
            .where(
                ResearchResult.id == ref.result_id,
                ResearchResult.project_id == project.id,
                ResearchResult.archived_at.is_(None),
                ResearchResultRevision.result_id == ref.result_id,
                ResearchResultRevision.project_id == project.id,
                ResearchResultRevision.id == ref.revision_id,
                ResearchResultRevision.content_hash == ref.content_hash,
            )
            .with_for_update(read=True, of=ResearchResult)
        )
        if head is None:
            raise ValidationAppError(
                "所选研究版本已更新或不可用", details={"code": "RESEARCH_CONTEXT_STALE"}
            )
        grants = await research_source_permissions(
            session, project.id, {ref.revision_id}, {"research", "external_processing"}, lock=True
        )
        if grants is None:
            raise ValidationAppError(
                "研究来源未允许本次导演解读", details={"code": "RESEARCH_CONTEXT_SOURCE_RESTRICTED"}
            )
    identity = await research_model_identity(session, project.workspace_id, resolution)
    destination = identity["destination_revision_id"]
    decision = await EgressAdmission(session).decide(
        project,
        purpose="research_text",
        required_purposes=["research_text", "director_text"],
        destination_id=UUID(str(destination)) if destination else None,
        processing_location=str(identity["processing_location"]),
    )
    if not decision.allowed:
        raise ValidationAppError(
            "项目外发策略禁止发送此研究版本", details={"code": decision.reason_code}
        )
    basis: dict[str, object] = {
        "ref": ref.model_dump(mode="json"),
        "model": identity,
        "source_grants": grants,
        "egress": decision.evidence(),
    }
    evidence = None
    if expected is not None:
        if basis != expected:
            raise ValidationAppError(
                "研究版本的发送依据已改变", details={"code": "RESEARCH_CONTEXT_STALE"}
            )
        body = public_body
        if isinstance(ref, ResearchDiscussionRef):
            body = await session.scalar(
                select(ResearchResultRevision.body).where(
                    ResearchResultRevision.id == ref.revision_id,
                    ResearchResultRevision.project_id == project.id,
                )
            )
        evidence = json.dumps(
            {"kind": head, "body": body}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(evidence) > 32000:
            raise ValidationAppError(
                "研究正文超出导演上下文上限", details={"code": "RESEARCH_CONTEXT_TOO_LARGE"}
            )
    return basis, decision, evidence


def discussion_messages(
    turn_id: UUID, ref: ResearchDiscussionRef | KnowledgeDiscussionRef, evidence: str
) -> list[AgentMessage]:
    """A server-performed read is untrusted tool data, never an instruction or a user utterance."""
    tool_name = (
        "read_pinned_knowledge"
        if isinstance(ref, KnowledgeDiscussionRef)
        else "read_selected_research"
    )
    call_id = f"source_{turn_id.hex}"
    return [
        AgentMessage(
            role="assistant",
            tool_calls=[
                AgentToolCall(
                    call_id=call_id,
                    name=tool_name,
                    arguments={"revision_id": str(ref.revision_id)},
                )
            ],
        ),
        AgentMessage(role="tool", tool_call_id=call_id, name=tool_name, content=evidence),
    ]
