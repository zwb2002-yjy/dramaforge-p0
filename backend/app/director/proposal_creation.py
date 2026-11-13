"""Persist Director proposal rows; callers retain payloads and user gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem


@dataclass(frozen=True, kw_only=True)
class ProposalItemDraft:
    command: str
    payload: dict[str, object]
    expected_target_version: int | None = None
    rationale: str = ""
    benefit: str = ""
    cost: str = ""
    risk: str = ""
    impact: str = ""


async def create_proposal(
    session: AsyncSession,
    *,
    thread: DirectorThread,
    scope_type: str,
    scope_entity_id: UUID,
    created_by: UUID,
    items: Sequence[ProposalItemDraft],
    applied_at: datetime | None = None,
) -> tuple[DirectorProposal, list[DirectorProposalItem]]:
    """Flush parent then items in input order, without committing or applying.

    Ownership comes from the caller-resolved thread, not individual item input.
    Scope may differ from the thread (editing uses a project thread). Persisted
    command ordering, such as Story's payload sort_order, belongs to the caller.
    applied_at only records an already-authorized delegation: applied proposal,
    accepted items. It does not authorize or execute anything.
    """
    proposal = DirectorProposal(
        project_id=thread.project_id,
        thread_id=thread.id,
        scope_type=scope_type,
        scope_entity_id=scope_entity_id,
        status="pending" if applied_at is None else "applied",
        created_by=created_by,
        decided_at=applied_at,
    )
    session.add(proposal)
    await session.flush()
    rows = [
        DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=proposal.project_id,
            command=item.command,
            payload=dict(item.payload),
            expected_target_version=item.expected_target_version,
            rationale=item.rationale,
            benefit=item.benefit,
            cost=item.cost,
            risk=item.risk,
            impact=item.impact,
            status="pending" if applied_at is None else "accepted",
            decided_at=applied_at,
        )
        for item in items
    ]
    session.add_all(rows)
    await session.flush()
    return proposal, rows
