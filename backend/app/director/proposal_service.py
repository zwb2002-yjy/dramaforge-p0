"""P7-07 Proposal partial apply service (03 §67).

Applies only the accepted proposal items via the typed command registry and
records per-item status. Rejected items are never executed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.proposal_commands import ProposalCommandError, ProposalCommandRegistry
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.shared.errors import ValidationAppError


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    decision: str = Field(pattern="^(accepted|rejected)$")


class PartialApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ProposalDecision] = Field(min_length=1)


class PartialApplyResult(BaseModel):
    accepted: list[UUID] = Field(default_factory=list)
    rejected: list[UUID] = Field(default_factory=list)
    failed: list[dict[str, object]] = Field(default_factory=list)


class ProposalService:
    def __init__(self, session: AsyncSession, *, actor: User) -> None:
        self._session = session
        self._actor = actor

    async def partial_apply(
        self,
        *,
        project: Project,
        proposal_id: UUID,
        apply_input: PartialApplyInput,
    ) -> PartialApplyResult:
        proposal = await self._session.scalar(
            select(DirectorProposal).where(
                DirectorProposal.id == proposal_id,
                DirectorProposal.project_id == project.id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if proposal is None:
            raise ValidationAppError(
                "proposal not found", details={"code": "PROPOSAL_NOT_FOUND"}
            )
        items = (
            await self._session.execute(
                select(DirectorProposalItem).where(
                    DirectorProposalItem.proposal_id == proposal.id
                ).execution_options(populate_existing=True)
            )
        ).scalars().all()
        by_id = {item.id: item for item in items}

        requested_ids = [decision.item_id for decision in apply_input.decisions]
        if len(requested_ids) != len(set(requested_ids)):
            raise ValidationAppError(
                "Each proposal item must have one decision",
                details={"code": "PROPOSAL_DUPLICATE_DECISION"},
            )
        registry = ProposalCommandRegistry(self._session, actor_id=self._actor.id)
        result = PartialApplyResult()
        changed = False
        for decision in apply_input.decisions:
            item = by_id.get(decision.item_id)
            if item is None:
                result.failed.append(
                    {"item_id": str(decision.item_id), "error": "unknown item"}
                )
                continue
            if item.status != "pending":
                if item.status == decision.decision:
                    decided = result.accepted if item.status == "accepted" else result.rejected
                    decided.append(item.id)
                else:
                    message = "item is stale" if item.status == "stale" else "item already decided"
                    result.failed.append({"item_id": str(item.id), "error": message})
                continue
            changed = True
            if decision.decision == "rejected":
                item.status = "rejected"
                item.decided_at = datetime.now(UTC)
                result.rejected.append(item.id)
                continue
            # accepted: execute via the typed command registry only
            try:
                await registry.apply(
                    project_id=project.id,
                    command=item.command,
                    payload=item.payload,
                    expected_target_version=item.expected_target_version,
                )
            except ProposalCommandError as exc:
                if exc.details.get("code") == "PROPOSAL_STALE":
                    item.status = "stale"
                    item.decided_at = datetime.now(UTC)
                result.failed.append(
                    {"item_id": str(item.id), "error": str(exc)}
                )
                continue
            item.status = "accepted"
            item.decided_at = datetime.now(UTC)
            result.accepted.append(item.id)

        if changed:
            has_accepted = any(item.status == "accepted" for item in items)
            proposal.status = "applied" if has_accepted else "decided"
            proposal.decided_at = datetime.now(UTC)
            await self._session.flush()
        await DirectorBusinessCheckpoints(self._session).reconcile_business_fact(
            project=project, proposal_id=proposal.id,
        )
        return result

    async def mark_proposals_stale_for_shot(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        current_version: int,
    ) -> int:
        """P7-08: after a manual edit, pending proposal items for the shot whose
        expected_target_version is behind become stale."""
        rows = (
            await self._session.execute(
                select(DirectorProposalItem)
                .join(DirectorProposal, DirectorProposal.id == DirectorProposalItem.proposal_id)
                .where(
                    DirectorProposal.project_id == project_id,
                    DirectorProposal.scope_type == "shot",
                    DirectorProposal.scope_entity_id == shot_id,
                    DirectorProposalItem.status == "pending",
                )
            )
        ).scalars().all()
        marked = 0
        for item in rows:
            if (
                item.expected_target_version is not None
                and item.expected_target_version < current_version
            ):
                item.status = "stale"
                item.decided_at = datetime.now(UTC)
                marked += 1
        await self._session.flush()
        return marked
