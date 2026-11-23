"""P7-07 Proposal partial apply service (03 §67).

Applies only the accepted proposal items via the typed command registry and
records per-item status. Rejected items are never executed.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.contracts.delivery_verification import DeliveryPlanRef
from app.contracts.domain_events import ProposalDecided
from app.director.business_flows import BusinessFlowService
from app.director.master_runs import MasterRunService
from app.director.proposal_commands import ProposalCommandError, ProposalCommandRegistry
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.story_arrangement import check_story_destination, check_story_replay
from app.production.application.events import append_production_notice
from app.shared.errors import ConflictError, ValidationAppError


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
        arrangement_plan: DeliveryPlanRef | None = None,
    ) -> PartialApplyResult:
        # Accepted commands may create project-keyed facts after editing a
        # target. Keep the common lock order Project -> proposal -> target.
        if any(decision.decision == "accepted" for decision in apply_input.decisions):
            await self._session.scalar(select(Project.id).where(Project.id == project.id)
                                       .with_for_update())
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
                    DirectorProposalItem.proposal_id == proposal.id,
                    DirectorProposalItem.project_id == project.id,
                ).with_for_update().execution_options(populate_existing=True)
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
        binding = None
        if arrangement_plan is not None:
            if any(not i.command.startswith("story.") for i in items):
                raise ValidationAppError("只有剧本提案可以用于分集安排")
            await check_story_destination(self._session, project.id, proposal.id, arrangement_plan)
            for decision in apply_input.decisions:
                prior = by_id.get(decision.item_id)
                if (
                    prior is not None
                    and prior.status == decision.decision == "accepted"
                    and prior.command == "story.upsert_episode"
                ):
                    await check_story_replay(self._session, prior, arrangement_plan)
            if any(
                (selected := by_id.get(d.item_id)) is not None and selected.status == "pending"
                for d in apply_input.decisions
            ):
                binding = await MasterRunService(
                    self._session,
                    actor=self._actor,
                    project=project,
                ).bind_plan_step(arrangement_plan, story=True)
        changed = False
        for decision in apply_input.decisions:
            item = by_id.get(decision.item_id)
            if item is None:
                result.failed.append({"item_id": str(decision.item_id), "error": "unknown item"})
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
                bound_episode = binding is not None and item.command == "story.upsert_episode"
                async with self._session.begin_nested() if bound_episode else nullcontext():
                    episode = await registry.apply(
                        project_id=project.id,
                        command=item.command,
                        payload=item.payload,
                        expected_target_version=item.expected_target_version,
                        command_key=f"proposal-item-{item.id}",
                        selected_item_id=item.id,
                    )
                    if bound_episode:
                        assert binding is not None
                        assert episode is not None
                        await BusinessFlowService(
                            self._session, actor=self._actor, project=project
                        ).record_episode_apply(
                            binding,
                            item,
                            episode,
                        )
            except (ProposalCommandError, ConflictError) as exc:
                if isinstance(exc, ConflictError) and not bound_episode:
                    raise
                if exc.details.get("code") == "PROPOSAL_STALE":
                    item.status = "stale"
                    item.decided_at = datetime.now(UTC)
                failure: dict[str, object] = {"item_id": str(item.id), "error": str(exc)}
                if exc.details.get("code"):
                    failure["code"] = exc.details["code"]
                result.failed.append(failure)
                continue
            item.status = "accepted"
            item.decided_at = datetime.now(UTC)
            result.accepted.append(item.id)

        if changed:
            pending_items = [it for it in items if it.status == "pending"]
            if not pending_items:
                has_accepted = any(item.status == "accepted" for item in items)
                proposal.status = "applied" if has_accepted else "decided"
                proposal.decided_at = datetime.now(UTC)
                await self._session.flush()
                await append_production_notice(
                    self._session, project_id=project.id, actor_id=self._actor.id,
                    notice=ProposalDecided(proposal_id=proposal.id),
                )
            else:
                await self._session.flush()
        return result
